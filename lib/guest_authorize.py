"""Guest SSH authorize: inject Clutch pubkeys, verify key SSH, disable password auth.

ADR-0030 / #524. Nest ``remoting_identity_id`` is never copied into guest authorize.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from lib import remoting_identities as ri
from lib.guest_health import check_ssh
from lib.guest_transport import (
    GuestTransport,
    GuestTransportError,
    SshGuestTransport,
    get_guest_transport,
)

log = logging.getLogger(__name__)


class GuestAuthorizeError(RuntimeError):
    """Raised when guest SSH authorize cannot complete."""


@dataclass(frozen=True)
class GuestAuthorizeResult:
    """Outcome of applying Clutch ``remoting.ssh.authorize`` on a guest."""

    authorize_ids: list[str]
    client_identity_id: str
    identity_file: str
    ssh_port: int
    skipped: bool = False
    skip_reason: str | None = None
    password_auth_disabled: bool = False


def authorize_ids_for_vm(vm) -> list[str]:
    """Return remoting.ssh.authorize ids from a VMConfig (defaults to hatchery)."""
    remoting = getattr(vm, "remoting", None)
    ssh = getattr(remoting, "ssh", None) if remoting is not None else None
    if ssh is None:
        return [ri.HATCHERY_IDENTITY_ID]
    return list(ssh.authorize)


def ssh_port_for_vm(vm) -> int:
    remoting = getattr(vm, "remoting", None)
    ssh = getattr(remoting, "ssh", None) if remoting is not None else None
    if ssh is None:
        return 22
    return int(ssh.port)


def resolve_authorize_pubkeys(authorize_ids: list[str]) -> list[tuple[str, str]]:
    """Resolve identity ids → (id, pubkey line). Raises on unknown/missing pubkey."""
    ids = [str(x).strip() for x in authorize_ids if str(x).strip()]
    if not ids:
        raise GuestAuthorizeError(
            "remoting.ssh.authorize is empty; at least one remoting identity id is required"
        )
    out: list[tuple[str, str]] = []
    for tid in ids:
        try:
            pub = ri.identity_pubkey(tid)
        except ri.RemotingIdentityError as exc:
            raise GuestAuthorizeError(str(exc)) from exc
        out.append((tid, pub))
    return out


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _inject_authorized_keys_ps(pubkeys: list[str]) -> str:
    """PowerShell: merge pubkeys into user + administrators authorized_keys."""
    lines = ",\n    ".join(_ps_quote(p) for p in pubkeys)
    return f"""
$ErrorActionPreference = 'Stop'
$pubkeys = @(
    {lines}
)
$userProfile = $env:USERPROFILE
if (-not $userProfile) {{ throw 'USERPROFILE is not set' }}
$userSsh = Join-Path $userProfile '.ssh'
$null = New-Item -ItemType Directory -Force -Path $userSsh
$userAk = Join-Path $userSsh 'authorized_keys'
$existing = @()
if (Test-Path -LiteralPath $userAk) {{
    $existing = @(Get-Content -LiteralPath $userAk -ErrorAction SilentlyContinue |
        ForEach-Object {{ $_.Trim() }} | Where-Object {{ $_ }})
}}
$merged = [System.Collections.Generic.List[string]]::new()
foreach ($line in ($existing + $pubkeys)) {{
    if ($line -and -not $merged.Contains($line)) {{ [void]$merged.Add($line) }}
}}
$merged | Set-Content -LiteralPath $userAk -Encoding ascii

$programData = $env:ProgramData
if ($programData) {{
    $adminSsh = Join-Path $programData 'ssh'
    $null = New-Item -ItemType Directory -Force -Path $adminSsh
    $adminAk = Join-Path $adminSsh 'administrators_authorized_keys'
    $adminExisting = @()
    if (Test-Path -LiteralPath $adminAk) {{
        $adminExisting = @(Get-Content -LiteralPath $adminAk -ErrorAction SilentlyContinue |
            ForEach-Object {{ $_.Trim() }} | Where-Object {{ $_ }})
    }}
    $adminMerged = [System.Collections.Generic.List[string]]::new()
    foreach ($line in ($adminExisting + $pubkeys)) {{
        if ($line -and -not $adminMerged.Contains($line)) {{ [void]$adminMerged.Add($line) }}
    }}
    $adminMerged | Set-Content -LiteralPath $adminAk -Encoding ascii
    # Win32-OpenSSH requires Administrators + SYSTEM only on this file.
    icacls $adminAk /inheritance:r | Out-Null
    icacls $adminAk /grant:r 'Administrators:F' /grant:r 'SYSTEM:F' | Out-Null
}}
Write-Output 'hatchery-authorize-ok'
""".strip()


def _disable_password_auth_ps() -> str:
    """PowerShell: set PasswordAuthentication no in sshd_config and restart sshd."""
    return r"""
$ErrorActionPreference = 'Stop'
$config = Join-Path $env:ProgramData 'ssh\sshd_config'
if (-not (Test-Path -LiteralPath $config)) {
    throw "sshd_config not found: $config"
}
$raw = Get-Content -LiteralPath $config -Raw
if ($null -eq $raw) { $raw = '' }
$updated = [regex]::Replace(
    $raw,
    '(?im)^\s*#?\s*PasswordAuthentication\s+\S+\s*$',
    'PasswordAuthentication no'
)
if ($updated -notmatch '(?im)^\s*PasswordAuthentication\s+no\s*$') {
    if ($updated.Length -gt 0 -and -not $updated.EndsWith("`n")) {
        $updated += "`n"
    }
    $updated += "PasswordAuthentication no`n"
}
if ($updated -notmatch '(?im)^\s*PubkeyAuthentication\s+') {
    if ($updated.Length -gt 0 -and -not $updated.EndsWith("`n")) {
        $updated += "`n"
    }
    $updated += "PubkeyAuthentication yes`n"
}
Set-Content -LiteralPath $config -Value $updated -Encoding ascii -NoNewline
Restart-Service -Name sshd -Force
Write-Output 'hatchery-password-auth-disabled'
""".strip()


def inject_authorized_keys(transport: GuestTransport, pubkeys: list[str]) -> None:
    """Install pubkeys on the guest via an authenticated Guest transport session."""
    if not pubkeys:
        raise GuestAuthorizeError("no public keys to inject")
    code, out = transport.run_ps(_inject_authorized_keys_ps(pubkeys), timeout=120)
    if code != 0 or "hatchery-authorize-ok" not in (out or ""):
        detail = (out or "").strip() or f"exit {code}"
        raise GuestAuthorizeError(f"failed to inject authorized_keys: {detail}")


def verify_key_ssh(
    host: str,
    username: str,
    identity_file: str,
    *,
    ssh_port: int = 22,
) -> None:
    """Probe guest SSH with BatchMode + identity path (no password)."""
    try:
        transport = get_guest_transport(
            host,
            username,
            "",
            kind="ssh",
            identity_file=identity_file,
            ssh_port=ssh_port,
        )
    except GuestTransportError as exc:
        raise GuestAuthorizeError(f"key SSH transport failed: {exc}") from exc
    if not isinstance(transport, SshGuestTransport):
        raise GuestAuthorizeError("expected SSH guest transport for key verify")
    try:
        code, out = transport.run_ps("Write-Output hatchery-guest-ok", timeout=15)
    except GuestTransportError as exc:
        raise GuestAuthorizeError(
            f"key SSH verify failed for {username}@{host}:{ssh_port} "
            f"(identity {identity_file}): {exc}"
        ) from exc
    if code != 0 or "hatchery-guest-ok" not in (out or ""):
        detail = (out or "").strip() or f"exit {code}"
        raise GuestAuthorizeError(
            f"key SSH verify failed for {username}@{host}:{ssh_port} "
            f"(identity {identity_file}): {detail}"
        )


def disable_password_authentication(transport: GuestTransport) -> None:
    """Disable guest SSH PasswordAuthentication after key verify succeeds."""
    code, out = transport.run_ps(_disable_password_auth_ps(), timeout=120)
    if code != 0 or "hatchery-password-auth-disabled" not in (out or ""):
        detail = (out or "").strip() or f"exit {code}"
        raise GuestAuthorizeError(f"failed to disable PasswordAuthentication: {detail}")


def apply_guest_ssh_authorize(
    host: str,
    username: str,
    password: str,
    *,
    authorize_ids: list[str],
    ssh_port: int = 22,
    password_transport: GuestTransport | None = None,
) -> GuestAuthorizeResult:
    """Inject → verify key SSH → disable password auth (ADR-0030 order).

    Uses ``password_transport`` (password SSH or WinRM) for inject/disable guest
    mutations. Controller client identity is the **first** authorize id (no
    round-robin). Skips when guest SSH TCP is not reachable.
    """
    resolved = resolve_authorize_pubkeys(authorize_ids)
    ids = [tid for tid, _ in resolved]
    pubkeys = [pub for _, pub in resolved]
    client_id = ids[0]
    identity_path = str(ri.identity_private_path(client_id))

    if not check_ssh(host, port=ssh_port):
        reason = f"Guest SSH not reachable on {host}:{ssh_port}; skipping authorize"
        log.info("%s", reason)
        return GuestAuthorizeResult(
            authorize_ids=ids,
            client_identity_id=client_id,
            identity_file=identity_path,
            ssh_port=ssh_port,
            skipped=True,
            skip_reason=reason,
        )

    transport = password_transport
    if transport is None:
        transport = get_guest_transport(
            host,
            username,
            password,
            ssh_port=ssh_port,
        )

    inject_authorized_keys(transport, pubkeys)
    verify_key_ssh(host, username, identity_path, ssh_port=ssh_port)

    # Prefer key SSH for the disable step when possible; fall back to the
    # password/WinRM transport that performed inject.
    disable_transport: GuestTransport
    try:
        disable_transport = get_guest_transport(
            host,
            username,
            "",
            kind="ssh",
            identity_file=identity_path,
            ssh_port=ssh_port,
        )
    except GuestTransportError:
        disable_transport = transport

    disable_password_authentication(disable_transport)
    return GuestAuthorizeResult(
        authorize_ids=ids,
        client_identity_id=client_id,
        identity_file=identity_path,
        ssh_port=ssh_port,
        password_auth_disabled=True,
    )
