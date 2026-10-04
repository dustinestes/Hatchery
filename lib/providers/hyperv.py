"""Hyper-V Nest provider (local PowerShell or remote Nest transport).

Lifecycle power/inventory/snapshots work locally or over Nest transport.
Hatch (``create_vm``) + Answer File DVD/ISO attach are Local Nest only until
Nest-cache ensure/copy lands (#215).
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from lib import answerfile as answerfile_lib
from lib.clutch import Firmware, VMConfig
from lib.nest_transport import NestTransportError, WinrmNestTransport
from lib.providers.base import BaseProvider
from lib.requirements import NestToolSpec
from lib.run_cmd import format_process_error, run_cmd

_JSON_MARKER = "HATCHERY_JSON:"

# Map Hyper-V ``VMState`` names to libvirt-style strings the UI already understands.
_STATE_MAP: dict[str, str] = {
    "Running": "running",
    "Off": "shut off",
    "Paused": "paused",
    "Saved": "shut off",
    "Starting": "running",
    "Stopping": "shut off",
    "Saving": "paused",
    "Restoring": "running",
}

_POWEROFF_ACTION_MAP: dict[str, str] = {
    "restart": "ShutDown",
    "destroy": "TurnOff",
    "shutdown": "ShutDown",
}

_SESSION_NOTES_PREFIX = "hatchery-session:"

_HYPERV_NEST_TOOLS: tuple[NestToolSpec, ...] = (
    NestToolSpec(
        name="Get-VM",
        required_for="Hyper-V VM lifecycle operations",
        packages={"windows": "Hyper-V"},
        check="hyperv_get_vm",
    ),
)


def _ps_quote(value: str) -> str:
    """Single-quote a string for PowerShell (escape embedded quotes)."""
    return "'" + value.replace("'", "''") + "'"


def _ps_encoded_command(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _local_powershell_exe() -> str:
    for name in ("pwsh", "powershell", "powershell.exe"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError(
        "PowerShell is required for a Local Hyper-V Nest (install pwsh or Windows PowerShell)"
    )


def _extract_json(stdout: str) -> Any:
    """Parse a ``HATCHERY_JSON:…`` line from PowerShell stdout."""
    for line in reversed((stdout or "").splitlines()):
        text = line.strip()
        if text.startswith(_JSON_MARKER):
            payload = text[len(_JSON_MARKER) :]
            if not payload:
                return None
            return json.loads(payload)
    stripped = (stdout or "").strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)
    raise RuntimeError("Hyper-V PowerShell returned no JSON payload")


def _normalize_list(data: Any) -> list[Any]:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


def _map_state(raw: str | None) -> str:
    if not raw:
        return "unknown"
    return _STATE_MAP.get(raw, raw.lower())


def _iso9660_name(basename: str, *, used: set[str]) -> str:
    """Return a unique ISO9660 path like ``/AUTOUNAT.;1`` for ``add_fp``."""
    stem = "".join(ch for ch in Path(basename).stem.upper() if ch.isalnum() or ch == "_")
    stem = (stem or "FILE")[:8]
    candidate = stem
    n = 1
    while candidate in used:
        suffix = str(n)
        candidate = (stem[: max(1, 8 - len(suffix))] + suffix)[:8]
        n += 1
    used.add(candidate)
    return f"/{candidate}.;1"


class HyperVProvider(BaseProvider):
    """Hyper-V Nest adapter via PowerShell (local or over Nest transport)."""

    supports_answer_file_attach: ClassVar[bool] = True

    def __init__(
        self,
        nest_id: str,
        *,
        transport=None,
        runner: Callable[[str], str] | None = None,
        iso_dir: Path | str | None = None,
        virtio_dir: Path | str | None = None,
        automation_dir: Path | str | None = None,
    ) -> None:
        self.nest_id = nest_id
        self._transport = transport
        self._runner = runner
        self.iso_dir = Path(iso_dir) if iso_dir is not None else Path()
        self.virtio_dir = Path(virtio_dir) if virtio_dir is not None else Path()
        self.automation_dir = Path(automation_dir) if automation_dir is not None else Path()

    @classmethod
    def nest_tool_specs(cls) -> list[NestToolSpec]:
        return list(_HYPERV_NEST_TOOLS)

    # ── PowerShell execution ──────────────────────────────────────────────────

    def _run_ps(self, script: str, *, timeout: float | None = 60) -> str:
        """Run PowerShell on the Nest; return stdout.

        ``runner`` (tests) wins. WinRM Nest transport runs script text as PowerShell.
        SSH Nest transport and Local Nest wrap ``-EncodedCommand``.
        """
        body = f"$ErrorActionPreference = 'Stop'\n{script}"
        if self._runner is not None:
            return self._runner(body)

        if self._transport is not None:
            try:
                if isinstance(self._transport, WinrmNestTransport):
                    return self._transport.run(body, timeout=timeout)
                encoded = _ps_encoded_command(body)
                remote = (
                    "powershell.exe -NoProfile -NonInteractive "
                    f"-ExecutionPolicy Bypass -EncodedCommand {encoded}"
                )
                return self._transport.run(remote, timeout=timeout)
            except NestTransportError as exc:
                raise RuntimeError(str(exc)) from exc

        exe = _local_powershell_exe()
        encoded = _ps_encoded_command(body)
        try:
            result = run_cmd(
                [
                    exe,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-EncodedCommand",
                    encoded,
                ],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(format_process_error(exc)) from exc
        return result.stdout or ""

    def _run_json(self, script: str, *, timeout: float | None = 60) -> Any:
        return _extract_json(self._run_ps(script, timeout=timeout))

    def _ack(self, script: str, *, timeout: float | None = 60) -> None:
        self._run_json(
            f"{script}\nWrite-Output '{_JSON_MARKER}{{\"ok\":true}}'",
            timeout=timeout,
        )

    # ── Path helpers ──────────────────────────────────────────────────────────

    def _resolve_media(self, filename: str, media_dir: Path) -> Path:
        path = Path(filename)
        if path.is_absolute():
            if not path.exists():
                raise FileNotFoundError(f"Media file not found: {path}")
            return path
        resolved = media_dir / filename
        if not resolved.exists():
            raise FileNotFoundError(f"Media file not found: {filename}")
        return resolved

    def _resolve_automation(self, filename: str) -> Path:
        path = Path(filename)
        if path.is_absolute():
            if not path.exists():
                raise FileNotFoundError(f"Automation file not found: {path}")
            return path
        resolved = self.automation_dir / filename
        if not resolved.exists():
            raise FileNotFoundError(
                f"answer_file not found in automation/answerfiles: {filename}\n"
                "Create or upload the Answer File via the Automations pane before hatching."
            )
        return resolved

    def _answer_iso_path(self, vm_name: str) -> Path:
        return Path(tempfile.gettempdir()) / f"{vm_name}-autounattend.iso"

    def _create_answer_iso(
        self,
        xml_content: str,
        vm_name: str,
        companions: list[tuple[str, str]] | None = None,
    ) -> Path:
        """Pack Autounattend.xml + companions into a Joliet ISO for Hyper-V DVD attach."""
        import pycdlib

        iso_path = self._answer_iso_path(vm_name)
        iso = pycdlib.PyCdlib()
        iso.new(interchange_level=3, joliet=3)
        used: set[str] = set()
        try:
            xml_bytes = xml_content.encode("utf-8")
            iso.add_fp(
                io.BytesIO(xml_bytes),
                len(xml_bytes),
                _iso9660_name("Autounattend.xml", used=used),
                joliet_path="/Autounattend.xml",
            )
            for basename, content in companions or []:
                raw = content.encode("utf-8")
                iso.add_fp(
                    io.BytesIO(raw),
                    len(raw),
                    _iso9660_name(basename, used=used),
                    joliet_path=f"/{basename}",
                )
            iso.write(str(iso_path))
        finally:
            iso.close()
        return iso_path

    # ── Hatch ─────────────────────────────────────────────────────────────────

    def prepare_answer_file_media(
        self,
        config: VMConfig,
        *,
        admin_password: str | None = None,
    ) -> Path | None:
        """Render the user Answer File and pack Autounattend + companions onto an ISO."""
        if not answerfile_lib.requires_answer_file(config.os):
            return None
        if not config.answer_file or not str(config.answer_file).strip():
            raise ValueError(
                f"Answer File is required for {config.os.value} guest "
                f"'{config.name}'. Select an Answer File on the Clutch "
                "before hatching."
            )
        answer_src = self._resolve_automation(config.answer_file)
        xml, companion_names = answerfile_lib.render_user_answer_file(
            answer_src,
            vm_name=config.name,
            admin_username=config.admin_username or "",
            admin_password=admin_password or "",
            user_params=dict(config.answer_file_parameters or {}),
        )
        companions: list[tuple[str, str]] = []
        for name in companion_names:
            companion_path = self._resolve_automation(name)
            companions.append((name, companion_path.read_text(encoding="utf-8")))
        return self._create_answer_iso(xml, config.name, companions)

    def create_vm(
        self,
        config: VMConfig,
        admin_password: str | None = None,
        storage_path: str | None = None,
    ) -> None:
        if self._transport is not None:
            raise RuntimeError(
                "Hyper-V hatch on a Remote Nest needs Nest-local media ensure/copy (#215); "
                "lifecycle power/snapshot ops are available over Nest transport"
            )
        if storage_path and not Path(storage_path).is_dir():
            raise FileNotFoundError(
                f"Storage path does not exist: {storage_path}\n"
                "Create the directory before hatching, or leave storage_path unset to use the "
                "hypervisor default."
            )
        if config.virtio_drivers:
            raise ValueError(
                "Hyper-V hatch does not attach VirtIO driver media yet; "
                "omit virtio_drivers on the Clutch for this Nest"
            )

        os_media = self._resolve_media(config.os_media, self.iso_dir)
        firmware = getattr(config, "firmware", None)
        tpm = bool(getattr(config, "tpm", None))
        if firmware == Firmware.BIOS or (
            isinstance(firmware, str) and str(firmware).lower() == "bios"
        ):
            generation = 1
            if tpm:
                raise ValueError("tpm: true requires firmware: uefi (Hyper-V Generation 2)")
        else:
            generation = 2

        answer_iso: Path | None = None
        try:
            answer_iso = self.prepare_answer_file_media(config, admin_password=admin_password)
            self._ack(
                self._build_create_script(
                    config,
                    os_media=os_media,
                    answer_iso=answer_iso,
                    storage_path=storage_path,
                    generation=generation,
                    tpm=tpm,
                ),
                timeout=300,
            )
        except Exception:
            if answer_iso and answer_iso.exists():
                answer_iso.unlink()
            raise

    def _build_create_script(
        self,
        config: VMConfig,
        *,
        os_media: Path,
        answer_iso: Path | None,
        storage_path: str | None,
        generation: int,
        tpm: bool,
    ) -> str:
        name_q = _ps_quote(config.name)
        os_q = _ps_quote(str(os_media))
        mem = int(config.ram_gb) * 1024 * 1024 * 1024
        disk_bytes = int(config.disk_gb) * 1024 * 1024 * 1024
        vcpus = int(config.vcpus)
        if storage_path:
            vhd_dir = _ps_quote(str(Path(storage_path)))
            vhd_expr = f"(Join-Path {vhd_dir} '{config.name}.vhdx')"
        else:
            vhd_expr = (
                f"(Join-Path (Get-VMHost).VirtualHardDiskPath {_ps_quote(config.name + '.vhdx')})"
            )
        answer_line = ""
        if answer_iso is not None:
            answer_line = f"Add-VMDvdDrive -VMName {name_q} -Path {_ps_quote(str(answer_iso))}\n"
        tpm_line = ""
        if generation == 2 and tpm:
            tpm_line = f"Enable-VMTPM -VMName {name_q}\n"
        secure_boot = ""
        if generation == 2:
            secure_boot = (
                f"Set-VMFirmware -VMName {name_q} -EnableSecureBoot On "
                f"-SecureBootTemplate MicrosoftWindows\n"
            )
        return f"""
$sw = Get-VMSwitch -Name 'Default Switch' -ErrorAction SilentlyContinue
if (-not $sw) {{ $sw = Get-VMSwitch | Select-Object -First 1 }}
if (-not $sw) {{ throw 'No Hyper-V virtual switch found on this Nest' }}
$vhdPath = {vhd_expr}
if (Test-Path -LiteralPath $vhdPath) {{
  throw "VHDX already exists: $vhdPath"
}}
New-VHD -Path $vhdPath -SizeBytes {disk_bytes} -Dynamic | Out-Null
$vm = New-VM -Name {name_q} -MemoryStartupBytes {mem} -Generation {generation} `
  -VHDPath $vhdPath -SwitchName $sw.Name
Set-VMProcessor -VMName {name_q} -Count {vcpus}
Set-VMMemory -VMName {name_q} -DynamicMemoryEnabled $false
Add-VMDvdDrive -VMName {name_q} -Path {os_q}
{answer_line}{secure_boot}{tpm_line}$dvd = Get-VMDvdDrive -VMName {name_q} | Select-Object -First 1
if ($dvd -and {generation} -eq 2) {{
  Set-VMFirmware -VMName {name_q} -FirstBootDevice $dvd
}}
Start-VM -Name {name_q}
"""

    def create_command_description(self, config: VMConfig, storage_path: str | None = None) -> str:
        os_media = Path(config.os_media)
        if not os_media.is_absolute():
            os_media = self.iso_dir / config.os_media
        gen = "Gen2" if getattr(config, "firmware", None) != Firmware.BIOS else "Gen1"
        where = storage_path or "Hyper-V default VHD path"
        return (
            f"Hyper-V New-VM '{config.name}' ({gen}, {config.vcpus} vCPU, "
            f"{config.ram_gb}GB RAM, {config.disk_gb}GB disk, ISO {os_media}, "
            f"storage {where})"
        )

    # ── Inventory ─────────────────────────────────────────────────────────────

    def list_vms(self) -> list[dict]:
        data = self._run_json(
            f"""
$vms = @(Get-VM | ForEach-Object {{
  [pscustomobject]@{{
    Name = $_.Name
    State = $_.State.ToString()
  }}
}})
Write-Output ('{_JSON_MARKER}' + (ConvertTo-Json -InputObject $vms -Compress -Depth 4))
"""
        )
        out: list[dict] = []
        for row in _normalize_list(data):
            name = str(row.get("Name") or "").strip()
            if not name:
                continue
            out.append({"name": name, "status": _map_state(row.get("State"))})
        return out

    def get_status(self, name: str) -> str:
        q = _ps_quote(name)
        data = self._run_json(
            f"""
$vm = Get-VM -Name {q}
Write-Output ('{_JSON_MARKER}' + (ConvertTo-Json -InputObject (@{{
  State = $vm.State.ToString()
}}) -Compress))
"""
        )
        if not isinstance(data, dict):
            raise RuntimeError(f"unexpected Hyper-V status payload for '{name}'")
        return _map_state(data.get("State"))

    # ── Power state ───────────────────────────────────────────────────────────

    def start_vm(self, name: str) -> None:
        self._ack(f"Start-VM -Name {_ps_quote(name)}")

    def stop_vm(self, name: str) -> None:
        self._ack(f"Stop-VM -Name {_ps_quote(name)} -Force")

    def force_stop_vm(self, name: str) -> None:
        self._ack(f"Stop-VM -Name {_ps_quote(name)} -TurnOff -Force")

    def pause_vm(self, name: str) -> None:
        self._ack(f"Suspend-VM -Name {_ps_quote(name)}")

    def resume_vm(self, name: str) -> None:
        self._ack(f"Resume-VM -Name {_ps_quote(name)}")

    def destroy_vm(self, name: str) -> None:
        q = _ps_quote(name)
        self._ack(
            f"""
$vm = Get-VM -Name {q}
$paths = @(Get-VMHardDiskDrive -VMName {q} | Select-Object -ExpandProperty Path)
Stop-VM -Name {q} -TurnOff -Force -ErrorAction SilentlyContinue
Remove-VM -Name {q} -Force
foreach ($p in $paths) {{
  if ($p -and (Test-Path -LiteralPath $p)) {{
    Remove-Item -LiteralPath $p -Force
  }}
}}
""",
            timeout=120,
        )
        answer_iso = self._answer_iso_path(name)
        if answer_iso.exists():
            answer_iso.unlink()

    # ── Snapshots (checkpoints) ───────────────────────────────────────────────

    def create_snapshot(self, name: str, label: str) -> None:
        self._ack(
            f"Checkpoint-VM -Name {_ps_quote(name)} -SnapshotName {_ps_quote(label)}",
            timeout=120,
        )

    def list_snapshots(self, name: str) -> list[str]:
        q = _ps_quote(name)
        data = self._run_json(
            f"""
$snaps = @(Get-VMSnapshot -VMName {q} | Select-Object -ExpandProperty Name)
Write-Output ('{_JSON_MARKER}' + (ConvertTo-Json -InputObject $snaps -Compress))
"""
        )
        return [str(s) for s in _normalize_list(data) if str(s).strip()]

    def revert_snapshot(self, name: str, label: str) -> None:
        self._ack(
            f"Restore-VMSnapshot -Name {_ps_quote(label)} "
            f"-VMName {_ps_quote(name)} -Confirm:$false",
            timeout=120,
        )

    def delete_snapshot(self, name: str, label: str) -> None:
        self._ack(
            f"Remove-VMSnapshot -VMName {_ps_quote(name)} -Name {_ps_quote(label)} -Confirm:$false",
            timeout=120,
        )

    # ── Identity / discovery ──────────────────────────────────────────────────

    def get_vm_ip(self, name: str) -> str | None:
        q = _ps_quote(name)
        try:
            data = self._run_json(
                f"""
$ips = @(Get-VMNetworkAdapter -VMName {q} | ForEach-Object {{ $_.IPAddresses }} |
  Where-Object {{ $_ -match '^\\d+\\.\\d+\\.\\d+\\.\\d+$' }})
$ip = if ($ips.Count -gt 0) {{ $ips[0] }} else {{ $null }}
Write-Output ('{_JSON_MARKER}' + (ConvertTo-Json -InputObject (@{{ Ip = $ip }}) -Compress))
"""
            )
        except RuntimeError:
            return None
        if not isinstance(data, dict):
            return None
        ip = data.get("Ip")
        return str(ip) if ip else None

    def get_vm_uuid(self, name: str) -> str | None:
        q = _ps_quote(name)
        try:
            data = self._run_json(
                f"""
$vm = Get-VM -Name {q} -ErrorAction Stop
Write-Output ('{_JSON_MARKER}' + (ConvertTo-Json -InputObject (@{{
  Id = $vm.Id.Guid
}}) -Compress))
"""
            )
        except RuntimeError:
            return None
        if not isinstance(data, dict):
            return None
        uid = data.get("Id")
        return str(uid) if uid else None

    def get_vm_name_by_uuid(self, uuid: str) -> str | None:
        q = _ps_quote(uuid)
        try:
            data = self._run_json(
                f"""
$vm = Get-VM | Where-Object {{ $_.Id.Guid -eq {q} }} | Select-Object -First 1
$name = if ($vm) {{ $vm.Name }} else {{ $null }}
Write-Output ('{_JSON_MARKER}' + (ConvertTo-Json -InputObject (@{{
  Name = $name
}}) -Compress))
"""
            )
        except RuntimeError:
            return None
        if not isinstance(data, dict):
            return None
        name = data.get("Name")
        return str(name) if name else None

    def send_key(self, name: str, key: str) -> None:
        raise RuntimeError(
            "Hyper-V does not support console key inject yet (send_key); "
            "use the guest console on the Nest host"
        )

    def set_poweroff_action(self, name: str, action: str) -> None:
        mapped = _POWEROFF_ACTION_MAP.get(action)
        if mapped is None:
            raise ValueError(
                f"unsupported Hyper-V poweroff action {action!r}; "
                f"expected one of {sorted(_POWEROFF_ACTION_MAP)}"
            )
        self._ack(
            f"Set-VM -Name {_ps_quote(name)} -AutomaticStopAction {mapped}",
        )

    # ── Session metadata (VM Notes) ───────────────────────────────────────────

    def tag_vm_session(self, vm_name: str, session_id: str, clutch_file: str) -> None:
        """Store hatch session metadata in Hyper-V VM Notes."""
        payload = json.dumps(
            {"session_id": session_id, "clutch_file": clutch_file},
            separators=(",", ":"),
        )
        notes = _SESSION_NOTES_PREFIX + payload
        self._ack(f"Set-VM -Name {_ps_quote(vm_name)} -Notes {_ps_quote(notes)}")

    def get_vm_session_tag(self, name: str) -> dict | None:
        q = _ps_quote(name)
        try:
            data = self._run_json(
                f"""
$vm = Get-VM -Name {q} -ErrorAction Stop
Write-Output ('{_JSON_MARKER}' + (ConvertTo-Json -InputObject (@{{
  Notes = [string]$vm.Notes
}}) -Compress))
"""
            )
        except RuntimeError:
            return None
        if not isinstance(data, dict):
            return None
        notes = str(data.get("Notes") or "")
        if not notes.startswith(_SESSION_NOTES_PREFIX):
            return None
        try:
            parsed = json.loads(notes[len(_SESSION_NOTES_PREFIX) :])
        except json.JSONDecodeError:
            return None
        sid = parsed.get("session_id")
        cf = parsed.get("clutch_file")
        if sid and cf:
            return {"session_id": str(sid), "clutch_file": str(cf)}
        return None
