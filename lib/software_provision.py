"""Guest Software staging and install walk over WinRM (#474).

Stages ``platforms/{os}/{arch}/`` payload contents into ``software_package(id)``,
then runs pre_install → install → post_install → detect (verify). Deep
offline/remote Nest upload polish tracks [#475](https://github.com/dustinestes/Hatchery/issues/475).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from collections.abc import Callable
from pathlib import Path, PureWindowsPath

from lib import provision as provision_lib
from lib import software as software_lib
from lib.clutch import GuestOS
from lib.guest_paths import GuestPaths, clutch_os_to_platform_key, guest_paths_for

log = logging.getLogger(__name__)

# Raw bytes per WinRM Send (stdin), not EncodedCommand. Putting payload in
# -EncodedCommand blows past Windows' ~8191 CreateProcess limit; stream via
# WinRM Send instead. After raising guest MaxEnvelopeSizekb to 8192, ~256 KiB
# raw fits comfortably under double-base64 + SOAP overhead.
_UPLOAD_CHUNK = 256_000
_UPLOAD_ATTEMPTS = 3
_WINRM_MAX_ENVELOPE_KB = 8192
_POWERSHELL_EXE = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

_TRANSIENT_UPLOAD_MARKERS = (
    "pipe has been ended",
    "wsmanfault_code': 109",
    'wsmanfault_code": 109',
    "connection reset",
    "connection aborted",
    "broken pipe",
)

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


def _ensure_winrm_envelope_size(
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    on_event: Callable[[str, str], None] | None = None,
) -> None:
    """Raise guest MaxEnvelopeSizekb when below the Software staging floor."""
    code = (
        f"$need = {_WINRM_MAX_ENVELOPE_KB}\n"
        "$cur = [int](Get-Item -Path 'WSMan:\\localhost\\MaxEnvelopeSizekb').Value\n"
        "if ($cur -lt $need) {\n"
        "  Set-Item -Path 'WSMan:\\localhost\\MaxEnvelopeSizekb' -Value $need\n"
        '  Write-Output "raised:$cur->$need"\n'
        "} else {\n"
        '  Write-Output "ok:$cur"\n'
        "}\n"
    )
    status, out = _run_ps(ip, admin_username, admin_password, code, timeout=60)
    if status != 0:
        raise RuntimeError(f"failed to ensure WinRM MaxEnvelopeSizekb: {out}")
    if on_event and out.startswith("raised:"):
        on_event(
            "INFO",
            f"Raised guest WinRM MaxEnvelopeSizekb for Software staging ({out})",
        )


def _upload_receiver_script(remote_path: str) -> str:
    """PowerShell that blocks on stdin lines (base64) until EOF, then writes the file.

    Uses StreamReader.ReadLine on [Console]::OpenStandardInput so the process stays
    alive until WinRM closes stdin. begin/process/end + bare ``powershell -encodedcommand``
    through cmd.exe exited early (WinRM fault 109 / 0-byte guest files).
    """
    return (
        "$ErrorActionPreference = 'Stop'\n"
        f"$path = {_ps_quote(remote_path)}\n"
        "$parent = Split-Path -Parent $path\n"
        "if ($parent) { $null = New-Item -Path $parent -ItemType Directory -Force }\n"
        "if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }\n"
        "$fd = [System.IO.File]::Create($path)\n"
        "$sha = [System.Security.Cryptography.SHA256]::Create()\n"
        "$stdin = [Console]::OpenStandardInput()\n"
        "$reader = New-Object System.IO.StreamReader("
        "$stdin, [System.Text.Encoding]::ASCII, $false)\n"
        "try {\n"
        "  while ($null -ne ($line = $reader.ReadLine())) {\n"
        "    $line = $line.Trim()\n"
        "    if (-not $line) { continue }\n"
        "    $bytes = [System.Convert]::FromBase64String($line)\n"
        "    [void]$sha.TransformBlock($bytes, 0, $bytes.Length, $bytes, 0)\n"
        "    $fd.Write($bytes, 0, $bytes.Length)\n"
        "  }\n"
        "} finally {\n"
        "  $reader.Dispose()\n"
        "  [void]$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)\n"
        "  $fd.Close()\n"
        "}\n"
        "$hash = [System.BitConverter]::ToString($sha.Hash)"
        ".Replace('-', '').ToLowerInvariant()\n"
        "Write-Output $hash\n"
    )


def _is_transient_winrm_upload_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _TRANSIENT_UPLOAD_MARKERS)


def _upload_file_once(
    ip: str,
    admin_username: str,
    admin_password: str,
    local_path: Path,
    remote_path: str,
    *,
    local_hash: str,
    size: int,
) -> None:
    script = _upload_receiver_script(remote_path)
    encoded_ps = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    # Receiver stays small; EncodedCommand must remain under ~8191 chars.
    if len(encoded_ps) >= 8191:
        raise RuntimeError(
            f"upload receiver EncodedCommand too long ({len(encoded_ps)}) for {remote_path}"
        )

    session = provision_lib._make_session(ip, admin_username, admin_password, timeout=600)
    protocol = session.protocol
    # UTF-8 shell; skip cmd.exe so stdin reaches powershell.exe directly.
    shell_id = protocol.open_shell(codepage=65001)
    try:
        command_id = protocol.run_command(
            shell_id,
            _POWERSHELL_EXE,
            ("-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_ps),
            console_mode_stdin=False,
            skip_cmd_shell=True,
        )
        try:
            if size == 0:
                protocol.send_command_input(shell_id, command_id, b"", end=True)
            else:
                offset = 0
                with local_path.open("rb") as fh:
                    while offset < size:
                        chunk = fh.read(_UPLOAD_CHUNK)
                        if not chunk:
                            break
                        offset += len(chunk)
                        # Double-encode: SOAP Send base64-wraps stdin; guest PS
                        # still expects base64 text lines on its stdin pipe.
                        payload = base64.b64encode(chunk) + b"\r\n"
                        protocol.send_command_input(
                            shell_id,
                            command_id,
                            payload,
                            end=(offset >= size),
                        )
            stdout, stderr, status = protocol.get_command_output(shell_id, command_id)
        finally:
            protocol.cleanup_command(shell_id, command_id)
    finally:
        protocol.close_shell(shell_id)

    out = provision_lib._strip_clixml(
        (stdout or b"").decode("utf-8", errors="replace")
        + "\n"
        + (stderr or b"").decode("utf-8", errors="replace")
    ).strip()
    if status != 0:
        raise RuntimeError(f"failed uploading {local_path.name} to {remote_path}: {out}")

    remote_hash = ""
    for line in out.splitlines():
        token = line.strip().lower()
        if len(token) == 64 and all(c in "0123456789abcdef" for c in token):
            remote_hash = token
            break
    if remote_hash != local_hash:
        raise RuntimeError(
            f"upload integrity check failed for {local_path.name}: "
            f"remote sha256 {remote_hash or '(missing)'} != local {local_hash} "
            f"(guest path {remote_path})"
        )


def _upload_file(
    ip: str,
    admin_username: str,
    admin_password: str,
    local_path: Path,
    remote_path: str,
    *,
    on_event: Callable[[str, str], None] | None = None,
) -> None:
    """Write a local file to the guest via WinRM stdin (chunked base64).

    Payload rides the WinRM Send stream, not -EncodedCommand, so chunks can be
    large without hitting the Windows command-line length limit. Verifies the
    remote SHA-256 against the local file before returning. Retries transient
    WinRM pipe/reset faults common right after guest reboot.
    """
    size = local_path.stat().st_size
    local_hash = hashlib.sha256(local_path.read_bytes()).hexdigest()
    last_exc: BaseException | None = None
    for attempt in range(1, _UPLOAD_ATTEMPTS + 1):
        try:
            _upload_file_once(
                ip,
                admin_username,
                admin_password,
                local_path,
                remote_path,
                local_hash=local_hash,
                size=size,
            )
            if attempt > 1 and on_event:
                on_event(
                    "INFO",
                    f"WinRM upload of {local_path.name} succeeded on attempt "
                    f"{attempt}/{_UPLOAD_ATTEMPTS}",
                )
            return
        except Exception as exc:
            last_exc = exc
            if attempt >= _UPLOAD_ATTEMPTS or not _is_transient_winrm_upload_error(exc):
                raise
            brief = str(exc).split("(extended fault")[0].strip().rstrip(".")
            if on_event:
                on_event(
                    "WARN",
                    f"WinRM upload of {local_path.name} failed "
                    f"(attempt {attempt}/{_UPLOAD_ATTEMPTS}): {brief}; retrying",
                )
            log.warning(
                "transient WinRM upload failure for %s (attempt %s/%s): %s",
                local_path.name,
                attempt,
                _UPLOAD_ATTEMPTS,
                exc,
            )
            time.sleep(5 * attempt)
    assert last_exc is not None
    raise last_exc


def stage_payload(
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    package_dir: Path,
    payload_rel: str | None,
    guest_package_dir: str,
    on_event: Callable[[str, str], None] | None = None,
) -> list[str]:
    """Copy payload tree contents into ``guest_package_dir`` (no nested os/arch).

    Returns relative paths uploaded (posix-style). Empty when there is no payload dir.
    """
    _ensure_winrm_envelope_size(ip, admin_username, admin_password, on_event=on_event)
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
        if on_event:
            on_event("INFO", f"Uploading {rel} ({path.stat().st_size} bytes)")
        _upload_file(ip, admin_username, admin_password, path, remote, on_event=on_event)
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
    """Run a package ``command`` or relative ``script`` with cwd = staged package dir.

    Slim transport contract: set location, run the authored snippet, return exit
    code + output. No installer heuristics, path rewriting, or cmd.exe wrapping.
    Guest instructions live in ``software.yaml`` (ADR-0025). Reserved path env
    vars for authors are tracked in #501.
    """
    pkg = _ps_quote(guest_package_dir)
    if command and script_rel:
        raise ValueError("pass exactly one of command or script_rel")
    if command:
        body = (
            f"Set-Location -LiteralPath {pkg}\n"
            "$LASTEXITCODE = $null\n"
            f"{command.rstrip()}\n"
            "if ($null -ne $LASTEXITCODE) { exit [int]$LASTEXITCODE }\n"
            "if (-not $?) { exit 1 }\n"
            "exit 0\n"
        )
    elif script_rel:
        # Relative path under staged payload; use guest path separators.
        rel = script_rel.replace("/", "\\").lstrip(".\\")
        script_path = _ps_quote(guest_package_dir.rstrip("\\") + "\\" + rel)
        body = (
            f"Set-Location -LiteralPath {pkg}\n"
            "$LASTEXITCODE = $null\n"
            f"& {script_path}\n"
            "if ($null -ne $LASTEXITCODE) { exit [int]$LASTEXITCODE }\n"
            "if (-not $?) { exit 1 }\n"
            "exit 0\n"
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
        on_event=emit,
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

    emit("INFO", f"Running install: {unit.install.command}")
    code, out = run_in_package(
        ip,
        admin_username,
        admin_password,
        guest_package_dir=guest_pkg,
        command=unit.install.command,
        timeout=900,
    )
    outputs.append(f"[install exit={code}]\n{out}")
    emit("INFO", f"Install finished with exit {code}")
    if not _exit_ok(code, unit.install.success_exit_codes):
        detail = (out or "").strip()
        raise RuntimeError(
            f"install failed with exit {code} (allowed {unit.install.success_exit_codes})"
            + (f": {detail}" if detail else "")
        )

    install_reboot = bool(unit.install.reboot_after)
    if install_reboot:
        emit("INFO", "Install requested reboot - waiting for LastBootUpTime change")
        provision_lib.reboot_guest_and_wait(ip, admin_username, admin_password, on_event=emit)

    run_hooks("post_install", unit.post_install)

    # Verify product presence via the package detect command. Hatch does not yet
    # use detect for skip-if-present; this is post-install integrity only.
    emit("INFO", "Running detect (verify install)")
    det_code, det_out = run_in_package(
        ip,
        admin_username,
        admin_password,
        guest_package_dir=guest_pkg,
        command=unit.detect.command,
        timeout=300,
    )
    outputs.append(f"[detect exit={det_code}]\n{det_out}")
    if not _exit_ok(det_code, unit.detect.success_exit_codes):
        raise RuntimeError(
            f"detect failed after install with exit {det_code} "
            f"(allowed {unit.detect.success_exit_codes}); "
            "install reported success but the product was not detected"
        )

    if clean_payload_on_success:
        emit("INFO", f"Cleaning staged package {guest_pkg}")
        remove_guest_package(ip, admin_username, admin_password, guest_pkg)

    return 0, "\n".join(outputs), install_reboot
