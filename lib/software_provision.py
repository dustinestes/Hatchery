"""Guest Software staging and install walk over WinRM (#474).

Stages ``platforms/{os}/{arch}/`` payload contents into ``software_package(id)``,
then runs pre_install → install → post_install. Deep offline/remote Nest upload
polish tracks [#475](https://github.com/dustinestes/Hatchery/issues/475).
"""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Callable
from pathlib import Path, PureWindowsPath

from lib import provision as provision_lib
from lib import software as software_lib
from lib.clutch import GuestOS
from lib.guest_health import check_winrm
from lib.guest_paths import GuestPaths, clutch_os_to_platform_key, guest_paths_for

log = logging.getLogger(__name__)

# Raw bytes per WinRM upload call. pywinrm sends PowerShell as -EncodedCommand
# (UTF-16LE → base64); Windows caps that command line at ~8191 chars. ~1 KiB raw
# keeps the encoded script comfortably under the limit (24 KiB chunks caused
# ERROR_FILENAME_EXCED_RANGE / "filename or extension is too long" on guests).
_UPLOAD_CHUNK = 1024

_ARCH_MAP = {
    "amd64": "x64",
    "x86_64": "x64",
    "x64": "x64",
    "x86": "x86",
    "i386": "x86",
    "i686": "x86",
    "arm64": "arm64",
    "aarch64": "arm64",
}


def detect_guest_arch(ip: str, admin_username: str, admin_password: str) -> str:
    """Return Software arch key (``x86`` / ``x64`` / ``arm64``) from the guest."""
    session = provision_lib._make_session(ip, admin_username, admin_password, timeout=30)
    result = session.run_ps(
        "Write-Output $env:PROCESSOR_ARCHITECTURE; Write-Output $env:PROCESSOR_ARCHITEW6432"
    )
    text = provision_lib._strip_clixml(result.std_out.decode("utf-8", errors="replace")).strip()
    lines = [ln.strip().lower() for ln in text.splitlines() if ln.strip()]
    # Prefer WOW64 host arch when present (32-bit process on 64-bit OS).
    for token in reversed(lines):
        mapped = _ARCH_MAP.get(token)
        if mapped:
            return mapped
    raise RuntimeError(f"could not map guest PROCESSOR_ARCHITECTURE from: {text!r}")


def _ps_quote(value: str) -> str:
    return provision_lib._ps_quote(value)


def _run_ps(
    ip: str,
    admin_username: str,
    admin_password: str,
    code: str,
    *,
    timeout: int = 300,
) -> tuple[int, str]:
    session = provision_lib._make_session(ip, admin_username, admin_password, timeout=timeout)
    result = session.run_ps(code)
    stdout = provision_lib._strip_clixml(result.std_out.decode("utf-8", errors="replace").strip())
    stderr = provision_lib._strip_clixml(result.std_err.decode("utf-8", errors="replace").strip())
    body = "\n".join(filter(None, [stdout, stderr]))
    return result.status_code, body


def _ensure_guest_dir(ip: str, admin_username: str, admin_password: str, remote_dir: str) -> None:
    code = f"$p = {_ps_quote(remote_dir)}\n$null = New-Item -Path $p -ItemType Directory -Force\n"
    code, out = _run_ps(ip, admin_username, admin_password, code, timeout=60)
    if code != 0:
        raise RuntimeError(f"failed to create guest directory {remote_dir}: {out}")


def _upload_file(
    ip: str,
    admin_username: str,
    admin_password: str,
    local_path: Path,
    remote_path: str,
) -> None:
    """Write a local file to the guest via chunked base64 WinRM."""
    data = local_path.read_bytes()
    # Controller may be Linux/macOS: use PureWindowsPath so backslash guests parse.
    parent = str(PureWindowsPath(remote_path).parent)
    # Ensure parent exists; truncate/create empty target.
    prep = (
        f"$parent = {_ps_quote(parent)}\n"
        "$null = New-Item -Path $parent -ItemType Directory -Force\n"
        f"$path = {_ps_quote(remote_path)}\n"
        "if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }\n"
        "$null = New-Item -Path $path -ItemType File -Force\n"
    )
    code, out = _run_ps(ip, admin_username, admin_password, prep, timeout=60)
    if code != 0:
        raise RuntimeError(f"failed to prepare guest file {remote_path}: {out}")

    if not data:
        return

    offset = 0
    while offset < len(data):
        chunk = data[offset : offset + _UPLOAD_CHUNK]
        b64 = base64.b64encode(chunk).decode("ascii")
        append = (
            f"$path = {_ps_quote(remote_path)}\n"
            f"$b64 = {_ps_quote(b64)}\n"
            "$bytes = [Convert]::FromBase64String($b64)\n"
            "$fs = [System.IO.File]::Open($path, [System.IO.FileMode]::Append, "
            "[System.IO.FileAccess]::Write)\n"
            "try { $fs.Write($bytes, 0, $bytes.Length) } finally { $fs.Dispose() }\n"
        )
        code, out = _run_ps(ip, admin_username, admin_password, append, timeout=120)
        if code != 0:
            raise RuntimeError(f"failed uploading {local_path.name} to {remote_path}: {out}")
        offset += len(chunk)


def stage_payload(
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    package_dir: Path,
    payload_rel: str | None,
    guest_package_dir: str,
) -> list[str]:
    """Copy payload tree contents into ``guest_package_dir`` (no nested os/arch).

    Returns relative paths uploaded (posix-style). Empty when there is no payload dir.
    """
    _ensure_guest_dir(ip, admin_username, admin_password, guest_package_dir)
    if not payload_rel:
        return []
    src = package_dir / payload_rel
    if not src.is_dir():
        # Unit may exist without offline files (command-only install).
        return []

    uploaded: list[str] = []
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src).as_posix()
        remote = str(PureWindowsPath(guest_package_dir).joinpath(*rel.split("/")))
        _upload_file(ip, admin_username, admin_password, path, remote)
        uploaded.append(rel)
    return uploaded


def _exit_ok(exit_code: int, success_codes: list[int]) -> bool:
    return exit_code in success_codes


def run_in_package(
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    guest_package_dir: str,
    command: str | None = None,
    script_rel: str | None = None,
    timeout: int = 600,
) -> tuple[int, str]:
    """Run a command or relative script with cwd = staged package dir."""
    pkg = _ps_quote(guest_package_dir)
    if command and script_rel:
        raise ValueError("pass exactly one of command or script_rel")
    if command:
        body = (
            f"Set-Location -LiteralPath {pkg}\n"
            f"{command}\n"
            "if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE } else { exit 0 }\n"
        )
    elif script_rel:
        # Relative path under staged payload; use guest path separators.
        rel = script_rel.replace("/", "\\").lstrip(".\\")
        script_path = _ps_quote(guest_package_dir.rstrip("\\") + "\\" + rel)
        body = (
            f"Set-Location -LiteralPath {pkg}\n"
            f"& {script_path}\n"
            "if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE } else { exit 0 }\n"
        )
    else:
        raise ValueError("command or script_rel is required")
    return _run_ps(ip, admin_username, admin_password, body, timeout=timeout)


def remove_guest_package(
    ip: str, admin_username: str, admin_password: str, guest_package_dir: str
) -> None:
    code = (
        f"$p = {_ps_quote(guest_package_dir)}\n"
        "if (Test-Path -LiteralPath $p) {\n"
        "  Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue\n"
        "}\n"
    )
    _run_ps(ip, admin_username, admin_password, code, timeout=120)


def run_software_entry(
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    package_id: str,
    guest_os: GuestOS | str,
    clean_payload_on_success: bool = True,
    on_event: Callable[[str, str], None] | None = None,
) -> tuple[int, str, bool]:
    """Execute one Software automation entry.

    Returns ``(exit_code, output, install_requested_reboot)``.
    When the install step sets ``reboot_after``, this function restarts the guest
    and waits for WinRM before ``post_install``. The third tuple value is True
    when that mid-walk reboot already happened (caller should not double-reboot
    for install alone; clutch-level ``reboot_after`` is still the caller's job).
    """

    def emit(level: str, message: str) -> None:
        if on_event:
            on_event(level, message)
        log.info("software[%s] %s: %s", package_id, level, message)

    paths: GuestPaths = guest_paths_for(guest_os)
    platform = clutch_os_to_platform_key(guest_os)
    pkg_path = software_lib.resolve_package_path(package_id)
    if pkg_path is None or not pkg_path.is_dir():
        raise FileNotFoundError(f"Software package not in Nest cache: {package_id}")

    def_path = pkg_path / software_lib.DEFINITION_FILENAME
    definition = software_lib.load_definition(def_path)

    arch = detect_guest_arch(ip, admin_username, admin_password)
    resolved = definition.resolve_unit(platform, arch)
    if resolved is None:
        raise RuntimeError(
            f"Software '{package_id}' has no platforms.{platform} unit for arch '{arch}' (or 'any')"
        )
    arch_used, unit = resolved
    payload_rel = f"{platform}/{arch_used}"
    guest_pkg = paths.software_package(package_id)

    emit("INFO", f"Staging payload {payload_rel} → {guest_pkg}")
    uploaded = stage_payload(
        ip,
        admin_username,
        admin_password,
        package_dir=pkg_path,
        payload_rel=payload_rel if (pkg_path / payload_rel).is_dir() else None,
        guest_package_dir=guest_pkg,
    )
    emit("INFO", f"Staged {len(uploaded)} file(s)")

    outputs: list[str] = []

    def run_hooks(label: str, hooks: list) -> None:
        for i, hook in enumerate(hooks):
            emit("INFO", f"Running {label}[{i}]")
            code, out = run_in_package(
                ip,
                admin_username,
                admin_password,
                guest_package_dir=guest_pkg,
                command=hook.command,
                script_rel=hook.script,
            )
            outputs.append(f"[{label}[{i}] exit={code}]\n{out}")
            if not _exit_ok(code, hook.success_exit_codes):
                raise RuntimeError(
                    f"{label}[{i}] failed with exit {code} (allowed {hook.success_exit_codes})"
                )

    run_hooks("pre_install", unit.pre_install)

    emit("INFO", "Running install")
    code, out = run_in_package(
        ip,
        admin_username,
        admin_password,
        guest_package_dir=guest_pkg,
        command=unit.install.command,
        timeout=900,
    )
    outputs.append(f"[install exit={code}]\n{out}")
    if not _exit_ok(code, unit.install.success_exit_codes):
        raise RuntimeError(
            f"install failed with exit {code} (allowed {unit.install.success_exit_codes})"
        )

    install_reboot = bool(unit.install.reboot_after)
    if install_reboot:
        emit("INFO", "Install requested reboot - restarting guest before post_install")
        provision_lib.restart_guest(ip, admin_username, admin_password)
        for _ in range(120):
            time.sleep(5)
            if check_winrm(ip):
                emit("INFO", "WinRM reconnected after install reboot")
                break
        else:
            raise RuntimeError("WinRM did not return after install reboot")

    run_hooks("post_install", unit.post_install)

    if clean_payload_on_success:
        emit("INFO", f"Cleaning staged package {guest_pkg}")
        remove_guest_package(ip, admin_username, admin_password, guest_pkg)

    return 0, "\n".join(outputs), install_reboot
