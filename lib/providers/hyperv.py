"""Hyper-V Nest provider (local PowerShell or remote Nest transport).

Lifecycle power, inventory, and snapshots for PR A of #213. Hatch
(``create_vm``) and Answer File attach land in a follow-on PR.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from collections.abc import Callable
from typing import Any, ClassVar

from lib.clutch import VMConfig
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


class HyperVProvider(BaseProvider):
    """Hyper-V Nest adapter via PowerShell (local or over Nest transport)."""

    supports_answer_file_attach: ClassVar[bool] = False

    def __init__(
        self,
        nest_id: str,
        *,
        transport=None,
        runner: Callable[[str], str] | None = None,
    ) -> None:
        self.nest_id = nest_id
        self._transport = transport
        self._runner = runner

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

    # ── Hatch (deferred) ──────────────────────────────────────────────────────

    def create_vm(
        self,
        config: VMConfig,
        admin_password: str | None = None,
        storage_path: str | None = None,
    ) -> None:
        raise RuntimeError(
            "Hyper-V hatch (create_vm) is not implemented yet; "
            "list/power/snapshot lifecycle is available (#213)"
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
