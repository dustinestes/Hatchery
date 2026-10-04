"""Guest-plane environment variables for hatch jobs (#501 / ADR-0026 / ADR-0032).

Reserved names map ADR-0025 path roles from ``guest_paths_for(GuestOS)`` - never
Controller ``sys.platform``. Values are guest-absolute paths (Windows or future
POSIX). Names are identical across guest OS families so ``software.yaml`` /
scripts can document one contract; shell syntax differs per unit
(``$env:NAME`` on Windows PowerShell, ``$NAME`` / ``export`` on Unix).

User Clutch ``environment`` entries merge on top for process env; keys must
not collide with reserved ``HATCHERY_*`` names or Hatchery-managed system env
(``PSModulePath`` append). Persisted vars use Machine/User scope on Windows.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Mapping, Sequence

from lib.clutch import EnvMode, EnvScope, GuestOS
from lib.guest_paths import GuestPaths, guest_os_family, guest_paths_for

if TYPE_CHECKING:
    from lib.clutch import EnvironmentEntry

# Always available for Script and Software jobs; reserved base also persisted.
RESERVED_BASE = (
    "HATCHERY_ROOT",
    "HATCHERY_LOGS",
    "HATCHERY_TEMP",
    "HATCHERY_SOFTWARE",
    "HATCHERY_MODULES",
)
# Set only for Software jobs (package-scoped); not persisted.
RESERVED_SOFTWARE = (
    "HATCHERY_SOFTWARE_PACKAGE",
    "HATCHERY_SOFTWARE_LOG",
)
# Job-only log path for Write-HatchEvent file append (not persisted).
RESERVED_JOB = ("HATCHERY_SCRIPT_LOG",)
# System env Hatchery appends during ensure; not a user Clutch key.
MANAGED_APPEND_ENV = ("PSModulePath",)
RESERVED_ALL = frozenset(RESERVED_BASE + RESERVED_SOFTWARE + RESERVED_JOB + MANAGED_APPEND_ENV)

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_reserved_name(name: str) -> bool:
    """True when ``name`` is a Hatchery-reserved guest env key (any casing)."""
    return (name or "").strip().upper() in {r.upper() for r in RESERVED_ALL}


def validate_user_environment(user_env: Mapping[str, str] | None) -> dict[str, str]:
    """Normalize and validate a flat name→value map (process env helper)."""
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
                f"environment key {key!r} is reserved for Hatchery "
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
    script_log: str | None = None,
) -> dict[str, str]:
    """Return reserved Hatchery env vars for a guest OS (and optional Software id)."""
    gp = paths or guest_paths_for(guest_os)
    env = {
        "HATCHERY_ROOT": gp.root,
        "HATCHERY_LOGS": gp.logs,
        "HATCHERY_TEMP": gp.temp,
        "HATCHERY_SOFTWARE": gp.software,
        "HATCHERY_MODULES": gp.modules,
    }
    if package_id:
        env["HATCHERY_SOFTWARE_PACKAGE"] = gp.software_package(package_id)
        env["HATCHERY_SOFTWARE_LOG"] = gp.software_log(package_id)
    if script_log:
        env["HATCHERY_SCRIPT_LOG"] = script_log
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


def powershell_job_preamble(env: Mapping[str, str]) -> str:
    """Process env + PSModulePath append for a job (outside the user script body)."""
    prefix = powershell_env_assignments(env)
    modules = (env or {}).get("HATCHERY_MODULES") or ""
    if modules:
        # Keep Hatchery modules discoverable even if Machine PSModulePath is stale
        # in this remoting process (WinPS and pwsh both read PSModulePath).
        prefix += (
            f"$__hatchMods = {_ps_quote(modules)}\n"
            "$env:PSModulePath = ("
            "@($env:PSModulePath -split ';' | "
            "Where-Object { $_ -and $_.Trim() }) + $__hatchMods | "
            "Select-Object -Unique"
            ") -join ';'\n"
        )
    return prefix


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
        {
            "name": "HATCHERY_SOFTWARE",
            "value": gp.software,
            "scope": "always",
            "persist": "machine",
        },
        {
            "name": "HATCHERY_MODULES",
            "value": gp.modules,
            "scope": "always",
            "persist": "machine",
        },
        {
            "name": "PSModulePath",
            "value": gp.modules,
            "scope": "always",
            "persist": "machine",
            "mode": "append",
        },
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
    family = guest_os_family(guest_os)
    if family == "windows":
        gp = guest_paths_for(guest_os)
        lines.append(f"PSModulePath → Machine (append {gp.modules})")
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
        '  Set-Item -Path "Env:$Name" -Value $next\n',
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
        '    [System.Runtime.InteropServices.DllImport("user32.dll", '
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
    )
    return "".join(lines)


def hatchery_module_relpath() -> str:
    """Guest-relative path under ``HATCHERY_ROOT`` for the Hatchery PowerShell module dir."""
    return r"modules\Hatchery"


def ensure_plan_summary(
    guest_os: GuestOS | str,
    entries: Sequence[EnvironmentEntry] | None = None,
) -> list[str]:
    """Human-readable catalog lines for the guest environment ensure job (#554)."""
    lines = persist_plan_summary(guest_os, entries)
    family = guest_os_family(guest_os)
    if family == "windows":
        gp = guest_paths_for(guest_os)
        lines.append(f"dirs → {gp.root} (logs/temp/software/modules)")
        lines.append(f"module → {gp.root}\\{hatchery_module_relpath()}\\Hatchery.psm1")
    else:
        label = family or "unknown"
        lines.append(f"payload → deferred ({label}; see follow-on issues)")
    return lines


def _reject_here_string_terminator(source: str, *, label: str) -> None:
    if "\n'@\n" in source or source.strip().endswith("'@"):
        raise ValueError(f"{label} must not contain a PowerShell here-string terminator")


def powershell_ensure_script(
    *,
    reserved: Mapping[str, str],
    entries: Sequence[EnvironmentEntry],
    module_psm1: str,
    module_psd1: str,
) -> str:
    """Windows ensure: persist env, dirs, Hatchery module, PSModulePath (#554)."""
    gp = guest_paths_for(GuestOS.WINDOWS)
    module_dir = rf"{gp.root}\{hatchery_module_relpath()}"
    psm1_path = rf"{module_dir}\Hatchery.psm1"
    psd1_path = rf"{module_dir}\Hatchery.psd1"
    _reject_here_string_terminator(module_psm1, label="module_psm1")
    _reject_here_string_terminator(module_psd1, label="module_psd1")
    persist = powershell_persist_script(reserved=reserved, entries=entries)
    return (
        persist
        + f"$root = {_ps_quote(gp.root)}\n"
        + f"$logs = {_ps_quote(gp.logs)}\n"
        + f"$temp = {_ps_quote(gp.temp)}\n"
        + f"$software = {_ps_quote(gp.software)}\n"
        + f"$modules = {_ps_quote(gp.modules)}\n"
        + f"$moduleDir = {_ps_quote(module_dir)}\n"
        + f"$psm1 = {_ps_quote(psm1_path)}\n"
        + f"$psd1 = {_ps_quote(psd1_path)}\n"
        + "foreach ($d in @($root, $logs, $temp, $software, $modules, $moduleDir)) {\n"
        + "  $null = New-Item -Path $d -ItemType Directory -Force\n"
        + "}\n"
        + "$psm1Body = @'\n"
        + module_psm1.rstrip()
        + "\n'@\n"
        + "$psd1Body = @'\n"
        + module_psd1.rstrip()
        + "\n'@\n"
        + "Set-Content -LiteralPath $psm1 -Value $psm1Body -Encoding UTF8\n"
        + "Set-Content -LiteralPath $psd1 -Value $psd1Body -Encoding UTF8\n"
        + 'if (-not (Test-Path -LiteralPath $psm1)) { throw "module missing: $psm1" }\n'
        + 'if (-not (Test-Path -LiteralPath $psd1)) { throw "manifest missing: $psd1" }\n'
        # Append modules dir to Machine PSModulePath without dropping defaults.
        # Empty Machine value is seeded from this process path (WinPS today; also
        # covers pwsh when ensure eventually runs under pwsh).
        + "$machinePath = [Environment]::GetEnvironmentVariable('PSModulePath', 'Machine')\n"
        + "if ([string]::IsNullOrWhiteSpace($machinePath)) { $machinePath = $env:PSModulePath }\n"
        + "$parts = @($machinePath -split ';' | Where-Object { $_ -and $_.Trim() })\n"
        + "if ($parts -notcontains $modules) {\n"
        + "  $next = ($parts + $modules) -join ';'\n"
        + "  [Environment]::SetEnvironmentVariable('PSModulePath', $next, 'Machine')\n"
        + "  $machinePath = $next\n"
        + "}\n"
        + "$userPath = [Environment]::GetEnvironmentVariable('PSModulePath', 'User')\n"
        + "$env:PSModulePath = (@($machinePath, $userPath) | "
        + "Where-Object { $_ -and $_.Trim() }) -join ';'\n"
        + "Import-Module Hatchery -Force\n"
        + "Get-Command Write-HatchEvent -ErrorAction Stop | Out-Null\n"
        # Optional pwsh 7 verify when installed (inherits process PSModulePath).
        + "if (Get-Command pwsh -ErrorAction SilentlyContinue) {\n"
        + "  & pwsh -NoProfile -NonInteractive -Command "
        + "'Import-Module Hatchery -Force; "
        + "Get-Command Write-HatchEvent -ErrorAction Stop | Out-Null'\n"
        + "  if ($LASTEXITCODE -ne 0) { throw 'pwsh could not import Hatchery module' }\n"
        + "}\n"
        + "foreach ($name in @("
        + "'HATCHERY_ROOT','HATCHERY_LOGS','HATCHERY_TEMP',"
        + "'HATCHERY_SOFTWARE','HATCHERY_MODULES'"
        + ")) {\n"
        + "  $v = [Environment]::GetEnvironmentVariable($name, 'Machine')\n"
        + '  if (-not $v) { throw "missing persisted Machine env: $name" }\n'
        + "}\n"
        + "$persistedMods = [Environment]::GetEnvironmentVariable('PSModulePath', 'Machine')\n"
        + "if (($persistedMods -split ';') -notcontains $modules) {\n"
        + '  throw "PSModulePath Machine missing Hatchery modules dir"\n'
        + "}\n"
        + "exit 0\n"
    )


def persist_guest_environment(
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    guest_os: GuestOS | str,
    entries: Sequence[EnvironmentEntry],
    timeout: int = 120,
) -> tuple[int, str]:
    """Persist reserved base + user persist entries on a Windows guest (SSH/WinRM)."""
    from lib import provision as provision_lib

    reserved = reserved_environment(guest_os)
    # Only persist reserved base (not software-scoped).
    reserved_base = {k: reserved[k] for k in RESERVED_BASE}
    body = powershell_persist_script(reserved=reserved_base, entries=list(entries)) + "exit 0\n"
    transport = provision_lib._guest_transport(ip, admin_username, admin_password)
    return transport.run_ps(body, timeout=timeout)


def ensure_guest_environment(
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    guest_os: GuestOS | str,
    entries: Sequence[EnvironmentEntry],
    timeout: int = 180,
) -> tuple[int, str]:
    """Run the Windows guest environment ensure job (#554).

    Linux/macOS return ``(0, 'skipped:…')`` until platform payloads land (#557 / #558).
    """
    from lib import provision as provision_lib

    family = guest_os_family(guest_os)
    if family != "windows":
        return 0, f"skipped:{family or 'unknown'}"

    reserved = reserved_environment(guest_os)
    reserved_base = {k: reserved[k] for k in RESERVED_BASE}
    body = powershell_ensure_script(
        reserved=reserved_base,
        entries=list(entries),
        module_psm1=provision_lib.hatchery_module_psm1_source(),
        module_psd1=provision_lib.hatchery_module_psd1_source(),
    )
    transport = provision_lib._guest_transport(ip, admin_username, admin_password)
    return transport.run_ps(body, timeout=timeout)
