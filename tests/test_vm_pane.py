"""VM inventory enrichment and provenance (#418 / #445)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

import hatchery as app_module
from lib import config as cfg
from lib import db


@pytest.fixture
def client(tmp_path):
    cfg.set_runtime_data_dir(tmp_path)
    cfg.init_data_dir()
    db.init_db(tmp_path / "hatchery.db")
    from lib import nests as nests_lib

    nests_lib.ensure_local_nest()
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def test_list_enriched_vms_marks_hatchery_sourced(client):
    from lib import vm_inventory as inv

    prov = MagicMock()
    prov.list_vms.return_value = [
        {"name": "hatched", "status": "running"},
        {"name": "foreign", "status": "shut off"},
    ]
    prov.get_vm_ip.return_value = None

    def _tag(name):
        if name == "hatched":
            return {"session_id": "s1", "clutch_file": "lab.yaml"}
        return None

    prov.get_vm_session_tag.side_effect = _tag

    with patch("lib.vm_inventory.get_provider", return_value=prov):
        rows = inv.list_enriched_vms("local")
    by_name = {r["name"]: r for r in rows}
    assert by_name["hatched"]["hatchery_sourced"] is True
    assert by_name["foreign"]["hatchery_sourced"] is False
    assert "resources" not in by_name["hatched"]


def test_filter_external():
    from lib import vm_inventory as inv

    rows = [
        {"name": "a", "hatchery_sourced": True},
        {"name": "b", "hatchery_sourced": False},
    ]
    assert len(inv.filter_external(rows, include_external=False)) == 1
    assert len(inv.filter_external(rows, include_external=True)) == 2


def test_api_vms_and_mutate(client):
    with (
        patch("lib.vm_inventory.get_provider") as mock_get,
        patch.object(cfg, "vms_show_external", return_value=True),
    ):
        prov = MagicMock()
        prov.list_vms.return_value = [{"name": "dc01", "status": "running"}]
        prov.get_vm_ip.return_value = None
        prov.get_vm_session_tag.return_value = None
        mock_get.return_value = prov
        resp = client.get("/api/vms")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "vms" in data
        assert data["vms"][0]["hatchery_sourced"] is False
        assert "resources" not in data["vms"][0]

    with patch("lib.vm_ops.get_provider") as mock_ops:
        mock_ops.return_value = MagicMock()
        resp = client.post("/api/nests/local/vms/dc01/start")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True


def test_vm_ops_lifecycle_and_snap():
    from lib import vm_ops as ops

    prov = MagicMock()
    with patch("lib.vm_ops.get_provider", return_value=prov):
        ops.start_vm("local", "dc01")
        ops.stop_vm("local", "dc01")
        ops.force_stop_vm("local", "dc01")
        ops.pause_vm("local", "dc01")
        ops.resume_vm("local", "dc01")
        ops.destroy_vm("local", "dc01")
        ops.take_snapshot("local", "dc01", "s1")
        ops.apply_snapshot("local", "dc01", "s1")
        ops.delete_snapshot("local", "dc01", "s1")
        prov.list_snapshots.return_value = ["s1"]
        assert ops.list_snapshots("local", "dc01") == ["s1"]
        with patch("lib.vm_ops.guest_health", return_value={"ip": "1.2.3.4", "winrm": True, "reachable": True}):
            assert ops.health_vm("local", "dc01")["reachable"] is True
    prov.start_vm.assert_called()
    prov.destroy_vm.assert_called_with("dc01")
    prov.create_snapshot.assert_called_with("dc01", "s1")


def test_vm_ops_errors():
    from lib import vm_ops as ops
    from lib.providers.factory import UnknownNestError, UnsupportedProviderError

    with patch("lib.vm_ops.get_provider", side_effect=UnknownNestError("nope")):
        with pytest.raises(ops.NestResolveError) as exc:
            ops.start_vm("missing", "dc01")
        assert exc.value.code == "not_found"

    with patch("lib.vm_ops.get_provider", side_effect=UnsupportedProviderError("remote")):
        with pytest.raises(ops.NestResolveError) as exc:
            ops.start_vm("remote1", "dc01")
        assert exc.value.code == "unavailable"

    prov = MagicMock()
    prov.start_vm.side_effect = RuntimeError("boom")
    with patch("lib.vm_ops.get_provider", return_value=prov):
        with pytest.raises(ops.ProviderActionError):
            ops.start_vm("local", "dc01")

    err = subprocess.CalledProcessError(
        1,
        ["utmctl", "pause", "guest"],
        stderr="error: disk image missing: /Nests/guest.qcow2\n",
    )
    prov2 = MagicMock()
    prov2.pause_vm.side_effect = err
    with patch("lib.vm_ops.get_provider", return_value=prov2):
        with pytest.raises(ops.ProviderActionError) as exc:
            ops.pause_vm("local", "guest")
    assert "disk image missing" in str(exc.value)
    assert "CalledProcessError" not in str(exc.value)


def test_api_vm_mutate_and_snap_routes(client):
    with patch("lib.vm_ops.get_provider") as mock_ops:
        prov = MagicMock()
        prov.list_snapshots.return_value = ["base"]
        mock_ops.return_value = prov
        assert client.post("/api/nests/local/vms/dc01/stop").status_code == 200
        assert client.post("/api/nests/local/vms/dc01/force-stop").status_code == 200
        assert client.post("/api/nests/local/vms/dc01/pause").status_code == 200
        assert client.post("/api/nests/local/vms/dc01/resume").status_code == 200
        assert client.post("/api/nests/local/vms/dc01/destroy").status_code == 200
        with patch("lib.vm_ops.guest_health", return_value={"ip": None, "winrm": False, "reachable": False}):
            assert client.get("/api/nests/local/vms/dc01/health").status_code == 200
        resp = client.get("/api/nests/local/vms/dc01/snapshots")
        assert resp.get_json()["snapshots"] == ["base"]
        assert (
            client.post(
                "/api/nests/local/vms/dc01/snapshots",
                json={"label": "snap1"},
            ).status_code
            == 200
        )
        assert client.post("/api/nests/local/vms/dc01/snapshots", json={}).status_code == 400
        assert client.post("/api/nests/local/vms/dc01/snapshots/snap1/apply").status_code == 200
        assert client.delete("/api/nests/local/vms/dc01/snapshots/snap1").status_code == 200


def test_vms_pane_markers(client):
    resp = client.get("/vms")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'aria-label="Filter VMs"' in html
    assert 'id="vms-nav"' in html
    assert 'data-vm-action="destroy"' in html
    assert ">Destroy<" in html
    assert ">Cull<" not in html
    assert 'id="vms-content-header"' in html
    assert "vms-lifecycle-actions" in html
    assert "vms-rollup" not in html
    assert 'id="vms-modal-backdrop"' in html
    assert "window.confirm" not in html
    assert "window.alert" not in html


def test_nests_pane_inventory_chrome(client):
    resp = client.get("/nests")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "inventory-toolbar" in html or "section-header inventory-toolbar" in html
    assert 'aria-label="Filter Nests"' in html
    assert 'id="nests-filter-q"' in html
    assert 'id="nests-filter-location"' in html
    assert 'id="nests-filter-provider"' in html
    assert "btn btn-primary btn-sm" in html
    assert "Manage Nests" in html
    assert "Open VMs pane" not in html
    assert "scripts-layout" in html
    assert "Select a Nest to inspect" in html
    assert 'aria-pressed="true"' not in html


def test_settings_display_has_external_vms_toggle(client):
    resp = client.get("/settings/display")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'name="vms_show_external"' in html
    assert "Show external VMs" in html
