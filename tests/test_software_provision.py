"""Unit tests for Software hatch staging helpers (#474)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from lib import software_provision as soft_prov


def test_detect_guest_arch_maps_amd64(monkeypatch):
    monkeypatch.setattr(
        soft_prov,
        "_run_ps",
        lambda *a, **k: (0, "AMD64\r\n"),
    )
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

    def fake_upload(ip, user, pw, local_path, remote_path, **kwargs):
        uploaded.append((Path(local_path).name, remote_path))

    class _Winrm:
        kind = "winrm"

    monkeypatch.setattr(soft_prov.provision_lib, "_guest_transport", lambda *a, **k: _Winrm())
    monkeypatch.setattr(soft_prov, "_ensure_winrm_envelope_size", lambda *a, **k: None)
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
    staged: list[str] = []
    monkeypatch.setattr(
        soft_prov,
        "stage_payload",
        lambda *a, **k: staged.append("staged") or ["a.msi"],
    )

    calls: list[str] = []
    detect_n = {"n": 0}

    def fake_run_in_package(*args, command=None, script_rel=None, **kwargs):
        calls.append(command or script_rel or "")
        if command and "detect" in command:
            detect_n["n"] += 1
            if detect_n["n"] == 1:
                return 1, "absent"
            return 0, "present"
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
        guest_os="windows",
        clean_payload_on_success=True,
        on_event=lambda level, msg: events.append((level, msg)),
    )
    assert code == 0
    assert reboot is False
    assert staged
    assert "echo install" in calls
    assert calls.count("echo detect") == 2
    assert cleaned
    assert any("detect (pre-install)" in m for _, m in events)
    assert any("Running install: windows.x64.install.command" in m for _, m in events)
    assert any("Staging" in m for _, m in events)
    assert any("verify install" in m for _, m in events)


def test_run_software_entry_skips_when_already_present(tmp_path, monkeypatch):
    pkg = tmp_path / "Pkg.1.0.0"
    pkg.mkdir()
    (pkg / "software.yaml").write_text(
        "hatchery:\n  publisher: P\n  product: Prod\n  version: '1.0.0'\n"
        "platforms:\n  windows:\n    any:\n"
        "      install:\n        command: echo install\n"
        "      uninstall:\n        command: echo u\n"
        "      detect:\n        command: echo detect\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(soft_prov.software_lib, "resolve_package_path", lambda _: pkg)
    monkeypatch.setattr(soft_prov, "detect_guest_arch", lambda *a, **k: "x64")

    staged: list[str] = []

    def boom_stage(*a, **k):
        staged.append("nope")
        raise AssertionError("stage_payload must not run when already present")

    monkeypatch.setattr(soft_prov, "stage_payload", boom_stage)

    calls: list[tuple[str | None, bool]] = []

    def fake_run(*args, command=None, require_cwd=True, **kwargs):
        calls.append((command, require_cwd))
        return 0, "present"

    monkeypatch.setattr(soft_prov, "run_in_package", fake_run)
    cleaned: list[str] = []
    monkeypatch.setattr(
        soft_prov,
        "remove_guest_package",
        lambda *a, **k: cleaned.append("cleaned"),
    )

    events: list[tuple[str, str]] = []
    code, out, reboot = soft_prov.run_software_entry(
        "10.0.0.1",
        "a",
        "b",
        package_id="Pkg.1.0.0",
        guest_os="windows",
        clean_payload_on_success=True,
        on_event=lambda level, msg: events.append((level, msg)),
    )
    assert code == 0
    assert reboot is False
    assert not staged
    assert not cleaned
    assert len(calls) == 1
    assert calls[0][0] == "echo detect"
    assert calls[0][1] is False
    assert "echo install" not in out
    assert any("already present" in m for _, m in events)


def test_run_software_entry_fails_when_detect_misses(tmp_path, monkeypatch):
    pkg = tmp_path / "Pkg.1.0.0"
    pkg.mkdir()
    (pkg / "software.yaml").write_text(
        "hatchery:\n  publisher: P\n  product: Prod\n  version: '1.0.0'\n"
        "platforms:\n  windows:\n    any:\n"
        "      install:\n        command: echo install\n"
        "      uninstall:\n        command: echo u\n"
        "      detect:\n        command: echo detect\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(soft_prov.software_lib, "resolve_package_path", lambda _: pkg)
    monkeypatch.setattr(soft_prov, "detect_guest_arch", lambda *a, **k: "x64")
    monkeypatch.setattr(soft_prov, "stage_payload", lambda *a, **k: [])

    detect_n = {"n": 0}

    def fake_run(*args, command=None, **kwargs):
        if command and "detect" in command:
            detect_n["n"] += 1
            return 1, "not installed"
        return 0, "ok"

    monkeypatch.setattr(soft_prov, "run_in_package", fake_run)
    monkeypatch.setattr(soft_prov, "remove_guest_package", lambda *a, **k: None)

    try:
        soft_prov.run_software_entry(
            "10.0.0.1",
            "a",
            "b",
            package_id="Pkg.1.0.0",
            guest_os="windows",
            clean_payload_on_success=True,
        )
        raise AssertionError("expected detect failure")
    except RuntimeError as exc:
        assert "detect failed after install" in str(exc)
    assert detect_n["n"] == 2


def test_run_in_package_command_and_script(monkeypatch):
    seen: list[str] = []

    def fake_run_ps(ip, user, pw, code, timeout=300):
        seen.append(code)
        return 0, "ok"

    monkeypatch.setattr(soft_prov, "_run_ps", fake_run_ps)
    # Slim contract: cwd + authored command (no cmd.exe wrapping)
    code, out = soft_prov.run_in_package(
        "10.0.0.1",
        "a",
        "b",
        guest_package_dir=r"C:\pkg",
        command=r"msiexec.exe /i .\foo.msi /qn",
    )
    assert code == 0
    assert "Set-Location" in seen[0]
    assert r"msiexec.exe /i .\foo.msi /qn" in seen[0]
    assert "cmd.exe" not in seen[0]
    soft_prov.run_in_package(
        "10.0.0.1",
        "a",
        "b",
        guest_package_dir=r"C:\pkg",
        command="exit 1",
        require_cwd=False,
    )
    assert "Test-Path" in seen[1]
    assert "Set-Location -LiteralPath" in seen[1]
    soft_prov.run_in_package(
        "10.0.0.1",
        "a",
        "b",
        guest_package_dir=r"C:\pkg",
        command="$pub='Hatchery'; exit 0",
    )
    assert "Set-Location" in seen[2]
    assert "$pub='Hatchery'" in seen[2]
    soft_prov.run_in_package(
        "10.0.0.1",
        "a",
        "b",
        guest_package_dir=r"C:\pkg",
        script_rel="hooks/pre.ps1",
    )
    assert "pre.ps1" in seen[3]
    assert "& " in seen[3]
    assert "Set-Location" in seen[3]
    soft_prov.run_in_package(
        "10.0.0.1",
        "a",
        "b",
        guest_package_dir=r"C:\pkg",
        command="msiexec.exe /i .\\foo.msi /l*v $env:HATCHERY_SOFTWARE_LOG",
        env={
            "HATCHERY_SOFTWARE_PACKAGE": r"C:\Program Files\Hatchery\software\Pkg.1.0.0",
            "HATCHERY_SOFTWARE_LOG": r"C:\Program Files\Hatchery\logs\software\Pkg.1.0.0.log",
            "MY_FLAG": "1",
        },
    )
    assert "$env:HATCHERY_SOFTWARE_LOG = " in seen[4]
    assert "$env:MY_FLAG = '1'" in seen[4]
    assert "Set-Location" in seen[4]
    # Env assignments precede cwd / command (slim runner; no cmd.exe wrap)
    assert seen[4].index("$env:HATCHERY_SOFTWARE_LOG") < seen[4].index("Set-Location")
    assert "cmd.exe" not in seen[4]


def test_upload_file_streams_stdin_chunks(tmp_path, monkeypatch):
    import base64
    import hashlib

    local = tmp_path / "blob.bin"
    data = b"abcdefghij"
    local.write_bytes(data)
    monkeypatch.setattr(soft_prov, "_UPLOAD_CHUNK", 4)
    digest = hashlib.sha256(data).hexdigest().encode()

    sends: list[tuple[bytes, bool]] = []
    protocol = MagicMock()
    protocol.open_shell.return_value = "shell-1"
    protocol.run_command.return_value = "cmd-1"
    protocol.get_command_output.return_value = (digest + b"\r\n", b"", 0)

    def capture_send(shell_id, command_id, stdin_input, end=False):
        sends.append((stdin_input, end))

    protocol.send_command_input.side_effect = capture_send
    session = MagicMock()
    session.protocol = protocol
    monkeypatch.setattr(soft_prov.provision_lib, "_make_session", lambda *a, **k: session)

    remote = r"C:\Program Files\Hatchery\software\Pkg\blob.bin"
    soft_prov._upload_file("10.0.0.1", "a", "b", local, remote)

    # 3 chunks (4+4+2); last Send closes stdin.
    assert len(sends) == 3
    assert sends[-1][1] is True
    assert all(s[0].endswith(b"\r\n") for s in sends)
    assert base64.b64decode(sends[0][0].strip()) == b"abcd"
    # powershell.exe + EncodedCommand args; payload not on the command line.
    assert protocol.open_shell.call_args.kwargs.get("codepage") == 65001
    run_args = protocol.run_command.call_args
    assert run_args[0][1] == soft_prov._POWERSHELL_EXE
    assert "-EncodedCommand" in run_args[0][2]
    assert run_args.kwargs.get("console_mode_stdin") is False
    assert run_args.kwargs.get("skip_cmd_shell") is True
    assert "OpenStandardInput" in soft_prov._upload_receiver_script(remote)
    protocol.close_shell.assert_called_once_with("shell-1")


def test_stage_payload_uses_ssh_when_resolved(tmp_path, monkeypatch):
    pkg = tmp_path / "Pkg"
    payload = pkg / "windows" / "x64"
    payload.mkdir(parents=True)
    (payload / "a.bin").write_bytes(b"x")
    ssh_uploads: list[str] = []

    class _Ssh:
        kind = "ssh"

    monkeypatch.setattr(soft_prov.provision_lib, "_guest_transport", lambda *a, **k: _Ssh())
    monkeypatch.setattr(soft_prov, "_ensure_guest_dir", lambda *a, **k: None)
    monkeypatch.setattr(
        soft_prov,
        "_upload_file_ssh",
        lambda transport, local, remote, **k: ssh_uploads.append(Path(local).name),
    )
    events: list[str] = []
    rels = soft_prov.stage_payload(
        "10.0.0.1",
        "a",
        "b",
        package_dir=pkg,
        payload_rel="windows/x64",
        guest_package_dir=r"C:\pkg",
        on_event=lambda lvl, msg: events.append(msg),
    )
    assert rels == ["a.bin"]
    assert ssh_uploads == ["a.bin"]
    assert any("SSH/SCP" in e for e in events)


def test_stage_payload_ensures_envelope(tmp_path, monkeypatch):
    pkg = tmp_path / "Pkg"
    payload = pkg / "windows" / "x64"
    payload.mkdir(parents=True)
    (payload / "a.bin").write_bytes(b"x")
    calls: list[str] = []

    class _Winrm:
        kind = "winrm"

    monkeypatch.setattr(soft_prov.provision_lib, "_guest_transport", lambda *a, **k: _Winrm())
    monkeypatch.setattr(
        soft_prov,
        "_ensure_winrm_envelope_size",
        lambda *a, **k: calls.append("envelope"),
    )
    monkeypatch.setattr(soft_prov, "_ensure_guest_dir", lambda *a, **k: calls.append("dir"))
    monkeypatch.setattr(
        soft_prov,
        "_upload_file",
        lambda *a, **k: calls.append("upload"),
    )
    soft_prov.stage_payload(
        "10.0.0.1",
        "a",
        "b",
        package_dir=pkg,
        payload_rel="windows/x64",
        guest_package_dir=r"C:\pkg",
    )
    assert calls == ["envelope", "dir", "upload"]


def test_upload_retries_transient_pipe_error(tmp_path, monkeypatch):
    import hashlib

    local = tmp_path / "blob.bin"
    data = b"abcdefghij"
    local.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    attempts = {"n": 0}
    events: list[tuple[str, str]] = []

    def fake_once(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError(
                "The pipe has been ended. (extended fault data: {'wsmanfault_code': 109})"
            )
        return None

    monkeypatch.setattr(soft_prov, "_upload_file_once", fake_once)
    monkeypatch.setattr(soft_prov.time, "sleep", lambda *_: None)
    soft_prov._upload_file(
        "10.0.0.1",
        "a",
        "b",
        local,
        r"C:\Pkg\blob.bin",
        on_event=lambda lvl, msg: events.append((lvl, msg)),
    )
    assert attempts["n"] == 2
    assert len(digest) == 64
    assert events[0][0] == "WARN"
    assert "attempt 1/3" in events[0][1]
    assert "retrying" in events[0][1]
    assert events[1][0] == "INFO"
    assert "succeeded on attempt 2/3" in events[1][1]


def test_upload_rejects_hash_mismatch(tmp_path, monkeypatch):
    local = tmp_path / "blob.bin"
    local.write_bytes(b"abcdefghij")
    protocol = MagicMock()
    protocol.open_shell.return_value = "shell-1"
    protocol.run_command.return_value = "cmd-1"
    protocol.get_command_output.return_value = (b"0" * 64 + b"\n", b"", 0)
    session = MagicMock()
    session.protocol = protocol
    monkeypatch.setattr(soft_prov.provision_lib, "_make_session", lambda *a, **k: session)

    try:
        soft_prov._upload_file("10.0.0.1", "a", "b", local, r"C:\Pkg\blob.bin")
        raise AssertionError("expected integrity failure")
    except RuntimeError as exc:
        assert "integrity check failed" in str(exc)


def test_upload_receiver_encoded_command_under_windows_limit():
    """Receiver script (not payload) must stay under CreateProcess ~8191 chars."""
    import base64

    remote = (
        r"C:\Program Files\Hatchery\software\Hatchery.SoftwareExample.1.0.0"
        r"\Hatchery.SoftwareExample.1.0.0-x64.msi"
    )
    script = soft_prov._upload_receiver_script(remote)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    assert len(encoded) < 8191, f"EncodedCommand length {len(encoded)} exceeds Windows limit"


def test_upload_empty_file_closes_stdin(tmp_path, monkeypatch):
    import hashlib

    local = tmp_path / "empty.bin"
    local.write_bytes(b"")
    digest = hashlib.sha256(b"").hexdigest().encode()
    protocol = MagicMock()
    protocol.open_shell.return_value = "shell-1"
    protocol.run_command.return_value = "cmd-1"
    protocol.get_command_output.return_value = (digest, b"", 0)
    session = MagicMock()
    session.protocol = protocol
    monkeypatch.setattr(soft_prov.provision_lib, "_make_session", lambda *a, **k: session)

    soft_prov._upload_file("10.0.0.1", "a", "b", local, r"C:\Pkg\empty.bin")
    protocol.send_command_input.assert_called_once_with("shell-1", "cmd-1", b"", end=True)
    assert protocol.run_command.call_args.kwargs.get("console_mode_stdin") is False
    assert protocol.run_command.call_args.kwargs.get("skip_cmd_shell") is True
    assert protocol.open_shell.call_args.kwargs.get("codepage") == 65001


def test_ensure_winrm_envelope_raises_when_low(monkeypatch):
    events: list[tuple[str, str]] = []

    def fake_run_ps(ip, user, pw, code, timeout=300):
        assert "MaxEnvelopeSizekb" in code
        return 0, "raised:500->8192"

    monkeypatch.setattr(soft_prov, "_run_ps", fake_run_ps)
    soft_prov._ensure_winrm_envelope_size(
        "10.0.0.1",
        "a",
        "b",
        on_event=lambda lvl, msg: events.append((lvl, msg)),
    )
    assert events[0][0] == "INFO"
    assert "MaxEnvelopeSizekb" in events[0][1]
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

    detect_n = {"n": 0}

    def fake_run(*args, command=None, **kwargs):
        if command and "echo d" in command:
            detect_n["n"] += 1
            if detect_n["n"] == 1:
                return 1, "absent"
            return 0, "present"
        if command == "msiexec":
            return 3010, "reboot pending"
        return 0, "ok"

    monkeypatch.setattr(soft_prov, "run_in_package", fake_run)
    monkeypatch.setattr(soft_prov, "remove_guest_package", lambda *a, **k: None)

    code, _, _ = soft_prov.run_software_entry(
        "10.0.0.1",
        "a",
        "b",
        package_id="Pkg.1.0.0",
        guest_os="windows",
        clean_payload_on_success=False,
    )
    assert code == 0
    assert detect_n["n"] == 2
