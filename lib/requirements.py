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
    """``which`` (PATH) or ``python3_gi`` (Debian python3-gi / import fallback)."""


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


def _tool_present(spec: NestToolSpec) -> bool:
    if spec.check == "python3_gi":
        return _check_python3_gi()
    return shutil.which(spec.name) is not None


def _requirement_from_spec(spec: NestToolSpec, *, present: bool, role: str = "nest") -> Requirement:
    package = package_for_current_os(spec.packages)
    return Requirement(
        name=spec.name,
        package=package,
        required_for=spec.required_for,
        present=present,
        optional=False,
        role=role,
        install_hint=install_hint(package) if not present and package else "",
    )


def has_remote_nests(nests: list[dict] | None = None) -> bool:
    """True when at least one Remote Nest is registered."""
    if nests is not None:
        return any((n.get("location") or "local") == "remote" for n in nests)
    try:
        from lib import nests as nests_lib

        rows = nests_lib.list_nests()
    except RuntimeError:
        # DB not initialized (early import / isolated unit tests)
        return False
    return any((n.get("location") or "local") == "remote" for n in rows)


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
        else:
            present = _remote_which(transport, spec.name)
        out.append(_requirement_from_spec(spec, present=present))
    return out


def check_nest(nest: dict, *, winrm_password: str | None = None) -> list[Requirement]:
    """Evaluate Nest capability tools for one Nest row."""
    from lib import nests as nests_lib
    from lib.nest_transport import get_nest_transport

    location = nest.get("location") or "local"
    provider = nest.get("provider_type") or nest.get("provider") or "libvirt"
    specs = nest_tool_specs_for_provider(provider)
    if not specs:
        return []

    if location == "local":
        return check_nest_tools_local(specs)

    transport_name = nest.get("transport") or "ssh"
    if transport_name == "winrm" and not (winrm_password or "").strip():
        # WinRM password is not stored (#110) — skip probe unless caller supplies it.
        return []

    try:
        connection = nests_lib.to_connection_config(nest, winrm_password=winrm_password)
        transport = get_nest_transport(connection)
    except (ValueError, TypeError):
        return [_requirement_from_spec(spec, present=False) for spec in specs]

    if transport is None:
        return check_nest_tools_local(specs)

    return check_nest_tools_remote(transport, specs)


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
        "swtpm",
        "python3-gi",
        "pwsh",
    )
    for name in legacy_names:
        resolve_prefix(f"{_LEGACY_REQUIREMENT_PREFIX} '{name}'")
