"""Unit tests for Software hatch staging helpers (#474)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from lib import software_provision as soft_prov


def test_detect_guest_arch_maps_amd64(monkeypatch):
    session = MagicMock()
    session.run_ps.return_value = MagicMock(
        std_out=b"AMD64\r\n",
        std_err=b"",
        status_code=0,
    )
    monkeypatch.setattr(soft_prov.provision_lib, "_make_session", lambda *a, **k: session)
    monkeypatch.setattr(soft_prov.provision_lib, "_strip_clixml", lambda t: t)
    assert soft_prov.detect_guest_arch("10.0.0.1", "admin", "pw") == "x64"


def test_exit_ok_membership():
    assert soft_prov._exit_ok(0, [0])
    assert soft_prov._exit_ok(3010, [0, 3010])
    assert not soft_prov._exit_ok(1, [0])


def test_stage_payload_uploads_files(tmp_path, monkeypatch):
    pkg = tmp_path / "Hatchery.SoftwareExample.1.0.0"
    payload = pkg / "windows" / "x64"
    payload.mkdir(parents=True)
    (payload / "Setup.msi").write_bytes(b"msi-bytes")

    uploaded: list[tuple[str, str]] = []

    def fake_upload(ip, user, pw, local_path, remote_path):
        uploaded.append((Path(local_path).name, remote_path))

    monkeypatch.setattr(soft_prov, "_ensure_guest_dir", lambda *a, **k: None)
    monkeypatch.setattr(soft_prov, "_upload_file", fake_upload)

    rels = soft_prov.stage_payload(
        "10.0.0.1",
        "admin",
        "pw",
        package_dir=pkg,
        payload_rel="windows/x64",
        guest_package_dir=r"C:\Program Files\Hatchery\software\Hatchery.SoftwareExample.1.0.0",
    )
    assert rels == ["Setup.msi"]
    assert uploaded[0][0] == "Setup.msi"
    assert uploaded[0][1].endswith(r"\Setup.msi")


def test_run_software_entry_happy_path(tmp_path, monkeypatch):
    pkg = tmp_path / "automation" / "software" / "Hatchery.SoftwareExample.1.0.0"
    (pkg / "windows" / "x64").mkdir(parents=True)
    (pkg / "windows" / "x64" / "a.msi").write_bytes(b"x")
    (pkg / "software.yaml").write_text(
        "hatchery:\n  publisher: Hatchery\n  product: SoftwareExample\n  version: '1.0.0'\n"
        "platforms:\n  windows:\n    x64:\n"
        "      install:\n        command: echo install\n"
        "      uninstall:\n        command: echo uninstall\n"
        "      detect:\n        command: echo detect\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        soft_prov.software_lib,
        "resolve_package_path",
        lambda package_id: pkg if package_id == "Hatchery.SoftwareExample.1.0.0" else None,
    )
    monkeypatch.setattr(soft_prov, "detect_guest_arch", lambda *a, **k: "x64")
    monkeypatch.setattr(soft_prov, "stage_payload", lambda *a, **k: ["a.msi"])

    calls: list[str] = []

    def fake_run_in_package(*args, command=None, script_rel=None, **kwargs):
        calls.append(command or script_rel or "")
        return 0, "ok"

    monkeypatch.setattr(soft_prov, "run_in_package", fake_run_in_package)
    cleaned: list[str] = []
    monkeypatch.setattr(
        soft_prov,
        "remove_guest_package",
        lambda *a, **k: cleaned.append(a[-1] if a else ""),
    )

    events: list[tuple[str, str]] = []
    code, _out, reboot = soft_prov.run_software_entry(
        "10.0.0.1",
        "admin",
        "pw",
        package_id="Hatchery.SoftwareExample.1.0.0",
        guest_os="win11",
        clean_payload_on_success=True,
        on_event=lambda level, msg: events.append((level, msg)),
    )
    assert code == 0
    assert reboot is False
    assert "echo install" in calls
    assert cleaned
    assert any("Staging" in m for _, m in events)


def test_run_in_package_command_and_script(monkeypatch):
    seen: list[str] = []

    def fake_run_ps(ip, user, pw, code, timeout=300):
        seen.append(code)
        return 0, "ok"

    monkeypatch.setattr(soft_prov, "_run_ps", fake_run_ps)
    code, out = soft_prov.run_in_package(
        "10.0.0.1",
        "a",
        "b",
        guest_package_dir=r"C:\pkg",
        command="echo hi",
    )
    assert code == 0
    assert "echo hi" in seen[0]
    soft_prov.run_in_package(
        "10.0.0.1",
        "a",
        "b",
        guest_package_dir=r"C:\pkg",
        script_rel="hooks/pre.ps1",
    )
    assert "pre.ps1" in seen[1]


def test_upload_file_chunks(tmp_path, monkeypatch):
    local = tmp_path / "blob.bin"
    local.write_bytes(b"abcdefghij")
    monkeypatch.setattr(soft_prov, "_UPLOAD_CHUNK", 4)
    codes: list[str] = []

    def fake_run_ps(ip, user, pw, code, timeout=300):
        codes.append(code)
        return 0, ""

    monkeypatch.setattr(soft_prov, "_run_ps", fake_run_ps)
    soft_prov._upload_file(
        "10.0.0.1",
        "a",
        "b",
        local,
        r"C:\Program Files\Hatchery\software\Pkg\blob.bin",
    )
    # prep + 3 chunks (4+4+2)
    assert len(codes) == 4
    assert "FromBase64String" in codes[1]


def test_remove_guest_package_runs_ps(monkeypatch):
    calls: list[str] = []

    def fake_run_ps(ip, user, pw, code, timeout=300):
        calls.append(code)
        return 0, ""

    monkeypatch.setattr(soft_prov, "_run_ps", fake_run_ps)
    soft_prov.remove_guest_package(
        "10.0.0.1", "a", "b", r"C:\Program Files\Hatchery\software\Pkg.1.0.0"
    )
    assert "Remove-Item" in calls[0]
    assert "Pkg.1.0.0" in calls[0]


def test_run_software_entry_honors_success_exit_codes(tmp_path, monkeypatch):
    pkg = tmp_path / "Pkg.1.0.0"
    pkg.mkdir()
    (pkg / "software.yaml").write_text(
        "hatchery:\n  publisher: P\n  product: Prod\n  version: '1.0.0'\n"
        "platforms:\n  windows:\n    any:\n"
        "      install:\n        command: msiexec\n        success_exit_codes: [0, 3010]\n"
        "      uninstall:\n        command: echo u\n"
        "      detect:\n        command: echo d\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(soft_prov.software_lib, "resolve_package_path", lambda _: pkg)
    monkeypatch.setattr(soft_prov, "detect_guest_arch", lambda *a, **k: "x64")
    monkeypatch.setattr(soft_prov, "stage_payload", lambda *a, **k: [])
    monkeypatch.setattr(soft_prov, "run_in_package", lambda *a, **k: (3010, "reboot pending"))
    monkeypatch.setattr(soft_prov, "remove_guest_package", lambda *a, **k: None)

    code, _, _ = soft_prov.run_software_entry(
        "10.0.0.1",
        "a",
        "b",
        package_id="Pkg.1.0.0",
        guest_os="win11",
        clean_payload_on_success=False,
    )
    assert code == 0
