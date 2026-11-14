"""Controller and Nest requirement checks (#208).

Controller checks stay on the Controller plane (UI/runtime + transport client).
Nest hypervisor tools are declared per provider and evaluated for Local Nests
on-box or for Remote Nests over Nest transport.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass
class Requirement:
    name: str
    package: str
    required_for: str
    present: bool
    optional: bool = False
    role: str = "controller"  # controller | nest
    install_hint: str = ""


@dataclass(frozen=True)
class NestToolSpec:
    """Provider-declared Nest-side tool (binary or special check)."""

    name: str
    required_for: str
    packages: dict[str, str] = field(default_factory=dict)
    """Install package names keyed by ``linux`` / ``macos`` / ``windows``."""
    check: str = "which"
    """``which`` (PATH), ``python3_gi``, or Hyper-V probes
    (``hyperv_feature`` / ``hyperv_module`` / ``hyperv_get_vm``)."""


CONTROLLER_ALERT_PREFIX = "Controller requirement:"
NEST_ALERT_PREFIX = "Nest capability:"
# Pre-#208 alert wording — resolve on Controller runs so Nest tools do not linger.
_LEGACY_REQUIREMENT_PREFIX = "Missing requirement:"

_OPTIONAL_CONTROLLER_TOOLS = [
    (
        "pwsh",
        {
            "linux": "powershell",
            "macos": "powershell",
            "windows": "Microsoft.PowerShell",
        },
        "Script parameter introspection - required to detect and configure automation script parameters",
    ),
]


def _os_key() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    return "linux"


def package_for_current_os(packages: dict[str, str]) -> str:
    """Return the best package name for this Controller OS."""
    key = _os_key()
    return packages.get(key) or packages.get("linux") or next(iter(packages.values()), "")


def install_hint(package: str) -> str:
    """Portable install hint (apt / brew / winget) — not apt-only."""
    if not package:
        return ""
    key = _os_key()
    if key == "macos":
        return f"brew install {package}"
    if key == "windows":
        return f"winget install {package}"
    return f"sudo apt install {package}"


def _check_python3_gi() -> bool:
    """Local Nest check for libvirt's virt-install GI dependency.

    Prefer ``dpkg-query`` on Debian/Ubuntu. Elsewhere try importing ``gi`` with
    the system interpreter when possible; otherwise treat as missing.
    """
    if shutil.which("dpkg-query") is not None:
        try:
            result = subprocess.run(
                ["dpkg-query", "--show", "--showformat=${Status}", "python3-gi"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return False
        if result.stdout.strip() == "install ok installed":
            return True
        return False
    try:
        import gi  # noqa: F401

        return True
    except ImportError:
        return False


_HYPERV_CHECKS = frozenset({"hyperv_feature", "hyperv_module", "hyperv_get_vm"})

_HYPERV_INSTALL_HINTS = {
    "hyperv_feature": (
        "Enable Hyper-V role/feature on the Nest "
        "(Server: Install-WindowsFeature Hyper-V; "
        "Client: Enable-WindowsOptionalFeature Microsoft-Hyper-V-All). "
        "Library script: enable-hyperv-windows.ps1"
    ),
    "hyperv_module": (
        "Install Hyper-V PowerShell management tools "
        "(Server: Hyper-V-PowerShell / IncludeManagementTools; "
        "Client: Microsoft-Hyper-V-Management-PowerShell)"
    ),
    "hyperv_get_vm": (
        "Hyper-V PowerShell module must expose Get-VM "
        "(install Hyper-V-PowerShell / management tools)"
    ),
}


def _tool_present(spec: NestToolSpec) -> bool:
    if spec.check == "python3_gi":
        return _check_python3_gi()
    if spec.check in _HYPERV_CHECKS:
        return _check_hyperv_local(spec.check)
    return shutil.which(spec.name) is not None


def _requirement_from_spec(spec: NestToolSpec, *, present: bool, role: str = "nest") -> Requirement:
    package = package_for_current_os(spec.packages)
    hint = ""
    if not present:
        hint = _HYPERV_INSTALL_HINTS.get(spec.check) or (install_hint(package) if package else "")
    return Requirement(
        name=spec.name,
        package=package,
        required_for=spec.required_for,
        present=present,
        optional=False,
        role=role,
        install_hint=hint,
    )


def _list_nests_or_empty() -> list[dict]:
    try:
        from lib import nests as nests_lib

        return list(nests_lib.list_nests())
    except RuntimeError:
        # DB not initialized (early import / isolated unit tests)
        return []


def remote_nest_count(nests: list[dict] | None = None) -> int:
    """Count registered Remote Nest rows."""
    rows = nests if nests is not None else _list_nests_or_empty()
    return sum(1 for n in rows if (n.get("location") or "local") == "remote")


def has_remote_nests(nests: list[dict] | None = None) -> bool:
    """True when at least one Remote Nest is registered."""
    return remote_nest_count(nests) > 0


@dataclass(frozen=True)
class ControllerInventoryRow:
    """Observable Controller-plane check for Settings inventory (#271)."""

    name: str
    status: str
    reason: str
    present: bool
    required_for: str
    package: str = ""
    install_hint: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "present": self.present,
            "required_for": self.required_for,
            "package": self.package,
            "install_hint": self.install_hint,
        }


def inventory_controller(*, nests: list[dict] | None = None) -> list[ControllerInventoryRow]:
    """What/if/why for every Controller check (always includes skipped SSH).

    Unlike :func:`check_controller`, this does not omit inactive checks - Settings
    shows the full inventory even when SSH is skipped (no Remote Nests / free HEAD).
    """
    rows: list[ControllerInventoryRow] = []
    remote_count = remote_nest_count(nests)
    ssh_pkg = package_for_current_os(
        {"linux": "openssh-client", "macos": "openssh", "windows": "OpenSSH.Client"}
    )
    ssh_present = shutil.which("ssh") is not None
    ssh_required_for = "Nest transport client for Remote Nests"
    if remote_count:
        noun = "Remote Nest" if remote_count == 1 else "Remote Nests"
        presence = "present" if ssh_present else "missing"
        rows.append(
            ControllerInventoryRow(
                name="ssh",
                status=f"Active - {presence}",
                reason=f"Required because {remote_count} {noun} registered",
                present=ssh_present,
                required_for=ssh_required_for,
                package=ssh_pkg,
                install_hint=install_hint(ssh_pkg) if not ssh_present else "",
            )
        )
    else:
        rows.append(
            ControllerInventoryRow(
                name="ssh",
                status="Skipped",
                reason="No Remote Nests registered",
                present=ssh_present,
                required_for=ssh_required_for,
                package=ssh_pkg,
                install_hint="",
            )
        )
    for name, packages, required_for in _OPTIONAL_CONTROLLER_TOOLS:
        pkg = package_for_current_os(packages)
        present = shutil.which(name) is not None
        presence = "present" if present else "missing"
        rows.append(
            ControllerInventoryRow(
                name=name,
                status=f"Optional - {presence}",
                reason=required_for,
                present=present,
                required_for=required_for,
                package=pkg,
                install_hint=install_hint(pkg) if not present else "",
            )
        )
    return rows


def check_controller(*, nests: list[dict] | None = None) -> list[Requirement]:
    """Tools needed on the Hatchery Controller (not Nest hypervisor packages)."""
    results: list[Requirement] = []
    if has_remote_nests(nests):
        pkg = package_for_current_os(
            {"linux": "openssh-client", "macos": "openssh", "windows": "OpenSSH.Client"}
        )
        present = shutil.which("ssh") is not None
        results.append(
            Requirement(
                name="ssh",
                package=pkg,
                required_for="Nest transport client for Remote Nests",
                present=present,
                optional=False,
                role="controller",
                install_hint=install_hint(pkg) if not present else "",
            )
        )
    for name, packages, required_for in _OPTIONAL_CONTROLLER_TOOLS:
        pkg = package_for_current_os(packages)
        present = shutil.which(name) is not None
        results.append(
            Requirement(
                name=name,
                package=pkg,
                required_for=required_for,
                present=present,
                optional=True,
                role="controller",
                install_hint=install_hint(pkg) if not present else "",
            )
        )
    return results


def check_all() -> list[Requirement]:
    """Controller requirement checks (#208). Nest tools use :func:`check_nest`."""
    return check_controller()


def nest_tool_specs_for_provider(provider_type: str) -> list[NestToolSpec]:
    """Return Nest tool specs for a registry provider type."""
    if provider_type == "libvirt":
        from lib.providers.libvirt import LibvirtProvider

        return list(LibvirtProvider.nest_tool_specs())
    if provider_type == "hyperv":
        from lib.providers.hyperv import HyperVProvider

        return list(HyperVProvider.nest_tool_specs())
    return []


def check_nest_tools_local(specs: list[NestToolSpec]) -> list[Requirement]:
    """Evaluate Nest tools on this device (Local Nest)."""
    return [_requirement_from_spec(spec, present=_tool_present(spec)) for spec in specs]


def _remote_which(transport, name: str) -> bool:
    """Return True if ``name`` is on PATH on the Nest (POSIX-style probe)."""
    # Prefer `command -v` (POSIX); fall back to `which`.
    script = f"command -v {name} >/dev/null 2>&1 || which {name} >/dev/null 2>&1"
    try:
        transport.run(script, timeout=15)
        return True
    except Exception:
        return False


def _hyperv_probe_script(check: str) -> tuple[str, str] | None:
    """Return ``(powershell_script, success_marker)`` for a Hyper-V Nest check."""
    if check == "hyperv_feature":
        marker = "hatchery-hyperv-feature-ok"
        script = (
            "$ok = $false\n"
            "if (Get-Command Get-WindowsFeature -ErrorAction SilentlyContinue) {\n"
            "  $f = Get-WindowsFeature -Name Hyper-V -ErrorAction SilentlyContinue\n"
            "  if ($f -and $f.InstallState -eq 'Installed') { $ok = $true }\n"
            "} elseif (Get-Command Get-WindowsOptionalFeature -ErrorAction SilentlyContinue) {\n"
            "  foreach ($n in @('Microsoft-Hyper-V-All','Microsoft-Hyper-V',"
            "'Microsoft-Hyper-V-Hypervisor')) {\n"
            "    $f = Get-WindowsOptionalFeature -Online -FeatureName $n "
            "-ErrorAction SilentlyContinue\n"
            "    if ($f -and $f.State -eq 'Enabled') { $ok = $true; break }\n"
            "  }\n"
            "}\n"
            f"if ($ok) {{ Write-Output '{marker}' }}\n"
        )
        return script, marker
    if check == "hyperv_module":
        marker = "hatchery-hyperv-module-ok"
        script = (
            "$ok = $false\n"
            "if (Get-Module -ListAvailable -Name Hyper-V) { $ok = $true }\n"
            "if (-not $ok -and (Get-Command Get-WindowsFeature -ErrorAction SilentlyContinue)) {\n"
            "  foreach ($n in @('Hyper-V-PowerShell','RSAT-Hyper-V-Tools')) {\n"
            "    $f = Get-WindowsFeature -Name $n -ErrorAction SilentlyContinue\n"
            "    if ($f -and $f.InstallState -eq 'Installed') { $ok = $true; break }\n"
            "  }\n"
            "}\n"
            "if (-not $ok -and (Get-Command Get-WindowsOptionalFeature "
            "-ErrorAction SilentlyContinue)) {\n"
            "  $f = Get-WindowsOptionalFeature -Online "
            "-FeatureName Microsoft-Hyper-V-Management-PowerShell "
            "-ErrorAction SilentlyContinue\n"
            "  if ($f -and $f.State -eq 'Enabled') { $ok = $true }\n"
            "}\n"
            f"if ($ok) {{ Write-Output '{marker}' }}\n"
        )
        return script, marker
    if check == "hyperv_get_vm":
        marker = "hatchery-hyperv-ok"
        script = f"Get-Command Get-VM -ErrorAction Stop | Out-Null; Write-Output '{marker}'"
        return script, marker
    return None


def _check_hyperv_local(check: str) -> bool:
    """True when local PowerShell passes a Hyper-V Nest prerequisite probe."""
    import base64

    probe = _hyperv_probe_script(check)
    if probe is None:
        return False
    script, marker = probe
    exe = shutil.which("pwsh") or shutil.which("powershell") or shutil.which("powershell.exe")
    if not exe:
        return False
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            [
                exe,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return marker in (result.stdout or "")


def _remote_hyperv_check(transport, check: str) -> bool:
    """Legacy remote Hyper-V probe helper (unused on free HEAD; Nest transport removed #620)."""
    import base64

    probe = _hyperv_probe_script(check)
    if probe is None:
        return False
    script, marker = probe
    try:
        # Duck-typed transport.run; WinRM-style callers pass raw PowerShell.
        if getattr(transport, "config", None) is not None and hasattr(
            getattr(transport, "config", None), "endpoint_url"
        ):
            out = transport.run(script, timeout=30)
        else:
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            out = transport.run(
                "powershell.exe -NoProfile -NonInteractive "
                f"-ExecutionPolicy Bypass -EncodedCommand {encoded}",
                timeout=30,
            )
    except Exception:
        return False
    return marker in (out or "")


# Backward-compatible aliases used by older tests / call sites.
def _check_hyperv_get_vm_local() -> bool:
    return _check_hyperv_local("hyperv_get_vm")


def _remote_hyperv_get_vm(transport) -> bool:
    return _remote_hyperv_check(transport, "hyperv_get_vm")


def check_nest_tools_remote(transport, specs: list[NestToolSpec]) -> list[Requirement]:
    """Evaluate Nest tools over Nest transport (Remote Nest)."""
    out: list[Requirement] = []
    for spec in specs:
        if spec.check == "python3_gi":
            # Probe the Nest for the Debian package or a python3 gi import.
            present = False
            try:
                transport.run(
                    "dpkg-query --show --showformat='${Status}' python3-gi 2>/dev/null "
                    "| grep -q 'install ok installed' "
                    "|| python3 -c 'import gi' 2>/dev/null",
                    timeout=20,
                )
                present = True
            except Exception:
                present = False
        elif spec.check in _HYPERV_CHECKS:
            present = _remote_hyperv_check(transport, spec.check)
        else:
            present = _remote_which(transport, spec.name)
        out.append(_requirement_from_spec(spec, present=present))
    return out


def check_nest(nest: dict, *, winrm_password: str | None = None) -> list[Requirement]:
    """Evaluate Nest capability tools for one Nest row (Local Nest on free HEAD)."""
    del winrm_password
    location = nest.get("location") or "local"
    provider = nest.get("provider_type") or nest.get("provider") or "libvirt"
    specs = nest_tool_specs_for_provider(provider)
    if not specs:
        return []

    if location == "local":
        return check_nest_tools_local(specs)

    # Remote Nest capability over Nest transport removed (#620).
    return [_requirement_from_spec(spec, present=False) for spec in specs]


def pwsh_available() -> bool:
    return shutil.which("pwsh") is not None


def missing(checks: list[Requirement]) -> list[Requirement]:
    return [r for r in checks if not r.present and not r.optional]


def apt_install_command(missing_list: list[Requirement]) -> str:
    """Backward-compatible apt hint; prefer :attr:`Requirement.install_hint`."""
    required = [r for r in missing_list if not r.optional]
    if not required:
        return ""
    packages = " ".join(r.package for r in required if r.package)
    if not packages:
        return ""
    return f"sudo apt install {packages}"


def resolve_legacy_requirement_alerts(resolve_prefix) -> None:
    """Clear pre-#208 ``Missing requirement:`` alerts for Nest tools moved off Controller."""
    legacy_names = (
        "virsh",
        "virt-install",
        "qemu-img",
        "virt-make-fs",
        "mformat",
        "mcopy",
        "swtpm",
        "python3-gi",
        "pwsh",
    )
    for name in legacy_names:
        resolve_prefix(f"{_LEGACY_REQUIREMENT_PREFIX} '{name}'")
