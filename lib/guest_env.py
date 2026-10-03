"""Guest-plane environment variables for hatch jobs (#501 / ADR-0026).

Reserved names map ADR-0025 path roles from ``guest_paths_for(GuestOS)`` - never
Controller ``sys.platform``. Values are guest-absolute paths (Windows or future
POSIX). Names are identical across guest OS families so ``software.yaml`` /
scripts can document one contract; shell syntax differs per unit
(``$env:NAME`` on Windows PowerShell, ``$NAME`` / ``export`` on Unix).

User Clutch ``environment`` entries merge on top for process injection; keys must
not collide with reserved ``HATCHERY_*`` names. Persisted vars use Machine/User
scope on Windows.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Mapping, Sequence

from lib.clutch import EnvMode, EnvScope, GuestOS
from lib.guest_paths import GuestPaths, guest_paths_for

if TYPE_CHECKING:
    from lib.clutch import EnvironmentEntry

# Always injected for Script and Software jobs; reserved base also persisted.
RESERVED_BASE = (
    "HATCHERY_ROOT",
    "HATCHERY_LOGS",
    "HATCHERY_TEMP",
    "HATCHERY_SOFTWARE",
)
# Injected only for Software jobs (package-scoped); not persisted.
RESERVED_SOFTWARE = (
    "HATCHERY_SOFTWARE_PACKAGE",
    "HATCHERY_SOFTWARE_LOG",
)
RESERVED_ALL = frozenset(RESERVED_BASE + RESERVED_SOFTWARE)

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_reserved_name(name: str) -> bool:
    """True when ``name`` is a Hatchery-reserved guest env key (any casing)."""
    return (name or "").strip().upper() in {r.upper() for r in RESERVED_ALL}


def validate_user_environment(user_env: Mapping[str, str] | None) -> dict[str, str]:
    """Normalize and validate a flat name→value map (process injection helper)."""
    if not user_env:
        return {}
    out: dict[str, str] = {}
    for raw_key, raw_val in user_env.items():
        key = str(raw_key or "").strip()
        if not key:
            raise ValueError("environment keys must not be empty")
        if not _ENV_NAME.fullmatch(key):
            raise ValueError(
                f"environment key {key!r} must be a portable identifier "
                "(letters, digits, underscore; not starting with a digit)"
            )
        if is_reserved_name(key):
            raise ValueError(
                f"environment key {key!r} is reserved for Hatchery path roles "
                f"({', '.join(sorted(RESERVED_ALL))})"
            )
        out[key] = str(raw_val if raw_val is not None else "")
    return out


def entries_to_process_map(entries: Sequence[EnvironmentEntry] | None) -> dict[str, str]:
    """Flatten structured environment entries to a process env map."""
    if not entries:
        return {}
    return validate_user_environment({e.name: e.value for e in entries})


def reserved_environment(
    guest_os: GuestOS | str,
    *,
    package_id: str | None = None,
    paths: GuestPaths | None = None,
) -> dict[str, str]:
    """Return reserved Hatchery env vars for a guest OS (and optional Software id)."""
    gp = paths or guest_paths_for(guest_os)
    env = {
        "HATCHERY_ROOT": gp.root,
        "HATCHERY_LOGS": gp.logs,
        "HATCHERY_TEMP": gp.temp,
        "HATCHERY_SOFTWARE": gp.software,
    }
    if package_id:
        env["HATCHERY_SOFTWARE_PACKAGE"] = gp.software_package(package_id)
        env["HATCHERY_SOFTWARE_LOG"] = gp.software_log(package_id)
    return env


def merge_guest_environment(
    reserved: Mapping[str, str],
    user_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Merge reserved + validated user env (reserved always wins on collision)."""
    user = validate_user_environment(user_env)
    return {**user, **dict(reserved)}


def powershell_env_assignments(env: Mapping[str, str]) -> str:
    """PowerShell lines that set ``$env:KEY`` for WinRM / Windows guests."""
    lines: list[str] = []
    for key, value in env.items():
        if not _ENV_NAME.fullmatch(key):
            raise ValueError(f"invalid env var name: {key!r}")
        escaped = value.replace("'", "''")
        lines.append(f"$env:{key} = '{escaped}'\n")
    return "".join(lines)


def posix_export_assignments(env: Mapping[str, str]) -> str:
    """Bourne-style ``export KEY=...`` lines for future SSH / Linux / macOS guests."""
    lines: list[str] = []
    for key, value in env.items():
        if not _ENV_NAME.fullmatch(key):
            raise ValueError(f"invalid env var name: {key!r}")
        escaped = value.replace("'", "'\"'\"'")
        lines.append(f"export {key}='{escaped}'\n")
    return "".join(lines)


def reserved_env_catalog(guest_os: GuestOS | str) -> list[dict[str, str]]:
    """UI helper: reserved base vars with example values for a guest OS."""
    gp = guest_paths_for(guest_os)
    rows = [
        {"name": "HATCHERY_ROOT", "value": gp.root, "scope": "always", "persist": "machine"},
        {"name": "HATCHERY_LOGS", "value": gp.logs, "scope": "always", "persist": "machine"},
        {"name": "HATCHERY_TEMP", "value": gp.temp, "scope": "always", "persist": "machine"},
        {"name": "HATCHERY_SOFTWARE", "value": gp.software, "scope": "always", "persist": "machine"},
        {
            "name": "HATCHERY_SOFTWARE_PACKAGE",
            "value": gp.software_package("{Publisher.Product.Version}"),
            "scope": "software",
            "persist": "job",
        },
        {
            "name": "HATCHERY_SOFTWARE_LOG",
            "value": gp.software_log("{Publisher.Product.Version}"),
            "scope": "software",
            "persist": "job",
        },
    ]
    return rows


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def persist_plan_summary(
    guest_os: GuestOS | str,
    entries: Sequence[EnvironmentEntry] | None = None,
) -> list[str]:
    """Human-readable lines describing what persist will write (for hatch events)."""
    lines: list[str] = []
    for key in RESERVED_BASE:
        lines.append(f"{key} → Machine (reserved)")
    for entry in entries or []:
        if not entry.persist:
            continue
        target = "User" if entry.scope == EnvScope.USER else "Machine"
        mode = entry.mode.value if hasattr(entry.mode, "value") else str(entry.mode)
        lines.append(f"{entry.name} → {target} ({mode})")
    return lines


def powershell_persist_script(
    *,
    reserved: Mapping[str, str],
    entries: Sequence[EnvironmentEntry],
) -> str:
    """Build PowerShell that persists reserved base + user persist entries.

    Uses ``[Environment]::SetEnvironmentVariable`` with Machine/User target.
    ``mode=append`` joins with ``;`` when a value already exists.
    """
    lines = [
        "$ErrorActionPreference = 'Stop'\n",
        "function Set-HatcheryEnv {\n",
        "  param([string]$Name, [string]$Value, [string]$Target, [string]$Mode)\n",
        "  $existing = [Environment]::GetEnvironmentVariable($Name, $Target)\n",
        "  if ($Mode -eq 'append' -and $existing) {\n",
        "    if (($existing -split ';') -contains $Value) { $next = $existing }\n",
        "    else { $next = ($existing.TrimEnd(';') + ';' + $Value) }\n",
        "  } else { $next = $Value }\n",
        "  [Environment]::SetEnvironmentVariable($Name, $next, $Target)\n",
        "  Set-Item -Path \"Env:$Name\" -Value $next\n",
        "}\n",
    ]
    for key, value in reserved.items():
        if key not in RESERVED_BASE:
            continue
        lines.append(
            f"Set-HatcheryEnv -Name {_ps_quote(key)} -Value {_ps_quote(value)} "
            f"-Target 'Machine' -Mode 'replace'\n"
        )
    for entry in entries:
        if not entry.persist:
            continue
        target = "User" if entry.scope == EnvScope.USER else "Machine"
        mode = "append" if entry.mode == EnvMode.APPEND else "replace"
        lines.append(
            f"Set-HatcheryEnv -Name {_ps_quote(entry.name)} -Value {_ps_quote(entry.value)} "
            f"-Target {_ps_quote(target)} -Mode {_ps_quote(mode)}\n"
        )
    # Notify other processes (best-effort).
    lines.append(
        "try {\n"
        "  Add-Type -Namespace HatcheryWin32 -Name Native -MemberDefinition @'\n"
        "    [System.Runtime.InteropServices.DllImport(\"user32.dll\", "
        "SetLastError=true, CharSet=System.Runtime.InteropServices.CharSet.Auto)]\n"
        "    public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, "
        "UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);\n"
        "'@ -ErrorAction SilentlyContinue\n"
        "  $HWND_BROADCAST = [IntPtr]0xffff\n"
        "  $WM_SETTINGCHANGE = 0x1A\n"
        "  $result = [UIntPtr]::Zero\n"
        "  [void][HatcheryWin32.Native]::SendMessageTimeout("
        "$HWND_BROADCAST, $WM_SETTINGCHANGE, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$result)\n"
        "} catch {}\n"
        "exit 0\n"
    )
    return "".join(lines)


def persist_guest_environment(
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    guest_os: GuestOS | str,
    entries: Sequence[EnvironmentEntry],
    timeout: int = 120,
) -> tuple[int, str]:
    """Persist reserved base + user persist entries on a Windows guest via WinRM."""
    from lib import provision as provision_lib

    reserved = reserved_environment(guest_os)
    # Only persist reserved base (not software-scoped).
    reserved_base = {k: reserved[k] for k in RESERVED_BASE}
    body = powershell_persist_script(reserved=reserved_base, entries=list(entries))
    session = provision_lib._make_session(ip, admin_username, admin_password, timeout)
    result = session.run_ps(body)
    stdout = provision_lib._strip_clixml(
        result.std_out.decode("utf-8", errors="replace").strip()
    )
    stderr = provision_lib._strip_clixml(
        result.std_err.decode("utf-8", errors="replace").strip()
    )
    body_out = "\n".join(filter(None, [stdout, stderr]))
    return result.status_code, body_out
