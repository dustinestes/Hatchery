"""Nest Health - gated reachability then Nest host resources / prerequisites (#538).

Reachability (``lib.nest_reachability``) is the first gate. Deeper probes (CPU,
memory, disks, Nest tool prerequisites) run only when the gate passes. Guest
health is a separate plane (``lib.guest_health``).
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib import config
from lib import nests as nests_lib
from lib import nest_reachability as nr
from lib import requirements as req_lib
from lib.nest_transport import get_nest_transport

log = logging.getLogger(__name__)

_SETTINGS_KEY = "nest_health_status"

# Free-space cues for nest_storage volumes (#538 / #50 follow-on).
_WARN_FREE_BYTES = 20 * 1024**3
_ERROR_FREE_BYTES = 10 * 1024**3
_WARN_FREE_RATIO = 0.15
_ERROR_FREE_RATIO = 0.05


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_snapshot() -> dict[str, Any]:
    return {"updated_at": None, "nests": {}}


def get_snapshot() -> dict[str, Any]:
    """Return last known Nest Health snapshot (may be empty before first run)."""
    raw = config.get().get(_SETTINGS_KEY)
    if not isinstance(raw, dict):
        return _empty_snapshot()
    nests = raw.get("nests") if isinstance(raw.get("nests"), dict) else {}
    return {
        "updated_at": raw.get("updated_at"),
        "nests": nests,
    }


def _save_snapshot(snap: dict[str, Any]) -> None:
    config.update_settings({_SETTINGS_KEY: snap})


def get_health(nest_id: str) -> dict[str, Any] | None:
    """Return persisted health for one Nest, or None."""
    entry = (get_snapshot().get("nests") or {}).get(nest_id)
    return dict(entry) if isinstance(entry, dict) else None


def record_health(nest: dict, result: dict[str, Any]) -> dict[str, Any]:
    """Merge one Nest Health result into the persisted snapshot."""
    nest_id = str(nest.get("id") or "").strip() or "?"
    snap = get_snapshot()
    nests = dict(snap.get("nests") or {})
    nests[nest_id] = result
    snap = {"updated_at": _utc_now(), "nests": nests}
    _save_snapshot(snap)
    return result


def prune_removed_nests(kept_ids: set[str]) -> None:
    """Drop health snapshot entries for Nest ids no longer in the registry."""
    snap = get_snapshot()
    nests = dict(snap.get("nests") or {})
    if not nests:
        return
    pruned = {nid: entry for nid, entry in nests.items() if nid in kept_ids}
    if pruned.keys() == nests.keys():
        return
    _save_snapshot({"updated_at": _utc_now(), "nests": pruned})


def volume_storage_status(
    path: str,
    disks: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Map a nest_storage path to free-space status against discovered disks.

    Returns ``status`` text: Connected | Disconnected | Warn | Error, plus
    matched disk stats when available.
    """
    path_text = (path or "").strip()
    out: dict[str, Any] = {
        "path": path_text,
        "status": "Disconnected",
        "free_bytes": None,
        "used_bytes": None,
        "total_bytes": None,
        "mount": None,
    }
    if not path_text or not disks:
        return out
    match = _match_disk_for_path(path_text, disks)
    if match is None:
        return out
    free_b = match.get("free_bytes")
    total_b = match.get("total_bytes")
    used_b = match.get("used_bytes")
    out.update(
        {
            "status": "Connected",
            "free_bytes": free_b,
            "used_bytes": used_b,
            "total_bytes": total_b,
            "mount": match.get("mount") or match.get("path"),
        }
    )
    if not isinstance(free_b, int) or not isinstance(total_b, int) or total_b <= 0:
        return out
    ratio = free_b / total_b
    if free_b < _ERROR_FREE_BYTES or ratio < _ERROR_FREE_RATIO:
        out["status"] = "Error"
    elif free_b < _WARN_FREE_BYTES or ratio < _WARN_FREE_RATIO:
        out["status"] = "Warn"
    return out


def _normalize_remote_path(path: str) -> str:
    """Normalize Nest path strings for prefix match (POSIX + Windows, Controller-OS-agnostic)."""
    text = (path or "").strip().replace("\\", "/")
    if not text:
        return ""
    # Drive letter case-fold (C: vs c:).
    if len(text) >= 2 and text[1] == ":":
        text = text[0].lower() + text[1:]
    while "//" in text:
        text = text.replace("//", "/")
    # Keep "c:/" as drive root; strip other trailing slashes.
    if text.endswith("/") and text not in ("/",) and not (len(text) == 3 and text[1] == ":"):
        text = text.rstrip("/")
    # Bare drive "c:" → "c:/" so children match with a boundary.
    if len(text) == 2 and text[1] == ":":
        text = text + "/"
    return text


def _path_under_root(target: str, root: str) -> bool:
    """True when ``target`` is ``root`` or a path under it (``/`` or ``\\`` separators)."""
    t = _normalize_remote_path(target)
    r = _normalize_remote_path(root)
    if not t or not r:
        return False
    if r == "/":
        return t.startswith("/")
    if t == r.rstrip("/"):
        return True
    prefix = r if r.endswith("/") else (r + "/")
    return t.startswith(prefix)


def _match_disk_for_path(path: str, disks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the longest mount/path prefix that covers ``path``."""
    best: dict[str, Any] | None = None
    best_len = -1
    for disk in disks:
        for key in ("mount", "path"):
            raw = disk.get(key)
            if not raw:
                continue
            root_s = _normalize_remote_path(str(raw))
            if not root_s:
                continue
            if _path_under_root(path, root_s) and len(root_s) > best_len:
                best = disk
                best_len = len(root_s)
    return best


def run_health(
    nest: dict,
    *,
    winrm_password: str | None = None,
    persist: bool = True,
    sync_alerts: bool = True,
) -> dict[str, Any]:
    """Run Nest Health for one Nest: gate, then deeper probes when gate ok."""
    checked_at = _utc_now()
    gate_result = nr.probe_nest(nest, winrm_password=winrm_password)
    gate = {
        "ok": bool(gate_result.ok),
        "detail": gate_result.detail or "",
        "failure_class": gate_result.failure_class,
    }

    if persist:
        nr.record_probe(nest, gate_result, checked_at=checked_at)
        if sync_alerts:
            nr.sync_alert_for_probe(nest, gate_result)

    result: dict[str, Any] = {
        "ok": bool(gate_result.ok),
        "checked_at": checked_at,
        "gate": gate,
        "deeper_ran": False,
        "cpu": None,
        "memory": None,
        "disks": [],
        "prerequisites": [],
        "nest_id": nest.get("id"),
        "name": nest.get("name") or nest.get("id"),
        "location": nest.get("location") or "local",
    }

    if not gate_result.ok:
        if persist:
            record_health(nest, result)
            _record_health_event(nest, result)
        return result

    result["deeper_ran"] = True
    resources = _gather_resources(nest, winrm_password=winrm_password)
    result["cpu"] = resources.get("cpu")
    result["memory"] = resources.get("memory")
    result["disks"] = resources.get("disks") or []

    prereqs = req_lib.check_nest(nest, winrm_password=winrm_password)
    result["prerequisites"] = [
        {
            "name": r.name,
            "present": bool(r.present),
            "optional": bool(r.optional),
            "required_for": r.required_for,
            "install_hint": r.install_hint or "",
            "package": r.package or "",
        }
        for r in prereqs
    ]

    if persist:
        record_health(nest, result)
        _record_health_event(nest, result)
    return result


def _record_health_event(nest: dict, result: dict[str, Any]) -> None:
    """Append a Nest Events line for a persisted Nest Health run (#611)."""
    from lib import nest_events as nest_events_lib

    nid = str(nest.get("id") or "").strip()
    if not nid:
        return
    gate = result.get("gate") or {}
    detail = (gate.get("detail") or "").strip()
    ok = bool(result.get("ok"))
    if ok:
        missing = [p["name"] for p in (result.get("prerequisites") or []) if not p.get("present")]
        if missing:
            level = "WARN"
            msg = f"Nest Health OK; missing prerequisites: {', '.join(missing)}"
        else:
            level = "INFO"
            msg = detail or "Nest Health OK"
    else:
        level = "ERROR"
        msg = detail or "Nest Health gate failed"
    nest_events_lib.record_controller(
        nid,
        topic="health",
        level=level,
        message=msg,
        component="nest_health",
    )


def run_as_validator(ctx, *, sync_alerts: bool = True) -> str:
    """Validator entry: Nest Health for one Nest or all registered Nests."""
    rows = nests_lib.list_nests()
    if getattr(ctx, "nest_id", None):
        rows = [n for n in rows if n.get("id") == ctx.nest_id]
    winrm_password = getattr(ctx, "winrm_password", None)
    checked = 0
    gate_down = 0
    for nest in rows:
        location = nest.get("location") or "local"
        transport_name = nest.get("transport") or "ssh"
        if (
            location == "remote"
            and transport_name == "winrm"
            and not (winrm_password or "").strip()
        ):
            continue
        result = run_health(
            nest,
            winrm_password=winrm_password,
            persist=True,
            sync_alerts=sync_alerts,
        )
        checked += 1
        if not result.get("ok"):
            gate_down += 1
            if sync_alerts:
                ctx.note_finding("alert")

    nr.record_last_run(checked=checked, down=gate_down)

    if checked == 0:
        return "No Nests probed"
    if gate_down:
        return f"{gate_down} of {checked} Nest(s) unreachable (Nest Health gate)"
    return f"All {checked} Nest(s) Nest Health OK"


def _gather_resources(
    nest: dict,
    *,
    winrm_password: str | None = None,
) -> dict[str, Any]:
    location = nest.get("location") or "local"
    if location == "local":
        return _gather_resources_local()

    transport_name = nest.get("transport") or "ssh"
    if transport_name == "winrm" and not (winrm_password or "").strip():
        return {"cpu": None, "memory": None, "disks": []}

    try:
        connection = nests_lib.to_connection_config(nest, winrm_password=winrm_password)
        transport = get_nest_transport(connection)
    except (ValueError, TypeError) as exc:
        log.debug("Nest Health resource gather config error: %s", exc)
        return {"cpu": None, "memory": None, "disks": []}

    if transport is None:
        return _gather_resources_local()

    provider = nest.get("provider_type") or nest.get("provider") or "libvirt"
    # Hyper-V Nests are Windows hosts; SSH still needs PowerShell probes (not POSIX df).
    if transport_name == "winrm" or provider == "hyperv":
        return _gather_resources_windows(transport)
    return _gather_resources_ssh(transport)


def _gather_resources_local() -> dict[str, Any]:
    return {
        "cpu": _local_cpu(),
        "memory": _local_memory(),
        "disks": _local_disks(),
    }


def _local_cpu() -> dict[str, Any] | None:
    count = os.cpu_count()
    if count is None:
        return None
    return {"count": int(count), "utilization_percent": None}


def _local_memory() -> dict[str, Any] | None:
    system = platform.system()
    if system == "Linux":
        return _parse_meminfo(Path("/proc/meminfo"))
    if system == "Darwin":
        return _local_memory_darwin()
    if system == "Windows":
        return _local_memory_windows()
    return None


def _parse_meminfo(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return _parse_meminfo_text(text)


def _parse_meminfo_text(text: str) -> dict[str, Any] | None:
    vals: dict[str, int] = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        key = parts[0].rstrip(":")
        try:
            vals[key] = int(parts[1]) * 1024  # kB → bytes
        except ValueError:
            continue
    total = vals.get("MemTotal")
    avail = vals.get("MemAvailable")
    if total is None:
        return None
    if avail is None:
        free = vals.get("MemFree") or 0
        buffers = vals.get("Buffers") or 0
        cached = vals.get("Cached") or 0
        avail = free + buffers + cached
    used = max(0, total - avail)
    return {"total_bytes": total, "used_bytes": used, "free_bytes": avail}


def _local_memory_darwin() -> dict[str, Any] | None:
    try:
        page_size = int(
            subprocess.run(
                ["pagesize"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            ).stdout.strip()
            or "4096"
        )
        vm = subprocess.run(
            ["vm_stat"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        total_pages = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    try:
        total = int((total_pages.stdout or "").strip())
    except ValueError:
        return None
    free_pages = 0
    for line in (vm.stdout or "").splitlines():
        if "Pages free" in line or "Pages speculative" in line:
            m = re.search(r"(\d+)", line.replace(".", ""))
            if m:
                free_pages += int(m.group(1))
    free = free_pages * page_size
    used = max(0, total - free)
    return {"total_bytes": total, "used_bytes": used, "free_bytes": free}


def _local_memory_windows() -> dict[str, Any] | None:
    # Prefer CIM via PowerShell when available (Controller on Windows).
    script = (
        "$o = Get-CimInstance Win32_OperatingSystem; "
        "@{total=[int64]$o.TotalVisibleMemorySize*1024; "
        "free=[int64]$o.FreePhysicalMemory*1024} | ConvertTo-Json -Compress"
    )
    for exe in ("pwsh", "powershell"):
        if shutil.which(exe) is None:
            continue
        try:
            proc = subprocess.run(
                [exe, "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        parsed = _parse_json_object(proc.stdout)
        if not parsed:
            continue
        total = parsed.get("total")
        free = parsed.get("free")
        if not isinstance(total, int) or not isinstance(free, int):
            continue
        return {
            "total_bytes": total,
            "free_bytes": free,
            "used_bytes": max(0, total - free),
        }
    return None


def _local_disks() -> list[dict[str, Any]]:
    system = platform.system()
    if system == "Windows":
        return _local_disks_windows()
    return _disks_from_df(_run_df_local())


def _run_df_local() -> str:
    try:
        proc = subprocess.run(
            ["df", "-B1", "-P"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout or ""


def _disks_from_df(stdout: str) -> list[dict[str, Any]]:
    """Parse POSIX ``df -B1 -P`` output into disk dicts."""
    disks: list[dict[str, Any]] = []
    lines = [ln for ln in (stdout or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return disks
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        filesystem, total_s, used_s, avail_s, _pct, mount = (
            parts[0],
            parts[1],
            parts[2],
            parts[3],
            parts[4],
            parts[5],
        )
        # Skip pseudo filesystems commonly present on Linux/macOS.
        if mount in {"/dev", "/dev/shm", "/run", "/sys", "/proc"} or mount.startswith(
            ("/sys/", "/proc/", "/run/", "/dev/")
        ):
            continue
        if filesystem.startswith(("tmpfs", "devtmpfs", "squashfs", "overlay")):
            continue
        try:
            total_b = int(total_s)
            used_b = int(used_s)
            free_b = int(avail_s)
        except ValueError:
            continue
        if total_b <= 0:
            continue
        disks.append(
            {
                "filesystem": filesystem,
                "mount": mount,
                "path": mount,
                "total_bytes": total_b,
                "used_bytes": used_b,
                "free_bytes": free_b,
                "state": "ok",
            }
        )
    return disks


def _local_disks_windows() -> list[dict[str, Any]]:
    script = (
        'Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | '
        "Select-Object DeviceID,Size,FreeSpace | ConvertTo-Json -Compress"
    )
    for exe in ("pwsh", "powershell"):
        if shutil.which(exe) is None:
            continue
        try:
            proc = subprocess.run(
                [exe, "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        return _disks_from_win_json(proc.stdout)
    return []


def _disks_from_win_json(stdout: str) -> list[dict[str, Any]]:
    data = _parse_json_value(stdout)
    if data is None:
        return []
    rows = data if isinstance(data, list) else [data]
    disks: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mount = str(row.get("DeviceID") or "").strip()
        try:
            total_b = int(row.get("Size") or 0)
            free_b = int(row.get("FreeSpace") or 0)
        except (TypeError, ValueError):
            continue
        if not mount or total_b <= 0:
            continue
        disks.append(
            {
                "filesystem": mount,
                "mount": mount,
                "path": mount + "\\" if not mount.endswith("\\") else mount,
                "total_bytes": total_b,
                "used_bytes": max(0, total_b - free_b),
                "free_bytes": free_b,
                "state": "ok",
            }
        )
    return disks


def _gather_resources_ssh(transport) -> dict[str, Any]:
    cpu = None
    memory = None
    disks: list[dict[str, Any]] = []
    try:
        nproc_out = transport.run(
            "nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo"
        )
        count = _parse_int_line(nproc_out)
        if count is not None and count > 0:
            cpu = {"count": count, "utilization_percent": None}
    except Exception as exc:
        log.debug("Nest Health remote nproc failed: %s", exc)

    try:
        mem_out = transport.run("cat /proc/meminfo 2>/dev/null || true")
        memory = _parse_meminfo_text(mem_out)
    except Exception as exc:
        log.debug("Nest Health remote meminfo failed: %s", exc)

    try:
        df_out = transport.run("df -B1 -P 2>/dev/null || true")
        disks = _disks_from_df(df_out)
    except Exception as exc:
        log.debug("Nest Health remote df failed: %s", exc)

    return {"cpu": cpu, "memory": memory, "disks": disks}


def _run_windows_ps(transport, script: str, *, timeout: float = 30) -> str:
    """Run PowerShell on a Windows Nest over WinRM or SSH (EncodedCommand)."""
    import base64

    from lib.nest_transport import WinrmNestTransport

    if isinstance(transport, WinrmNestTransport):
        return transport.run(script, timeout=timeout)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return transport.run(
        "powershell.exe -NoProfile -NonInteractive "
        f"-ExecutionPolicy Bypass -EncodedCommand {encoded}",
        timeout=timeout,
    )


def _gather_resources_windows(transport) -> dict[str, Any]:
    """CPU / memory / disks on a Windows Nest (Hyper-V via SSH or WinRM)."""
    cpu = None
    memory = None
    disks: list[dict[str, Any]] = []
    try:
        cpu_out = _run_windows_ps(
            transport,
            "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors",
        )
        count = _parse_int_line(cpu_out)
        if count is not None and count > 0:
            cpu = {"count": count, "utilization_percent": None}
    except Exception as exc:
        log.debug("Nest Health Windows CPU failed: %s", exc)

    try:
        mem_out = _run_windows_ps(
            transport,
            "$o = Get-CimInstance Win32_OperatingSystem; "
            "@{total=[int64]$o.TotalVisibleMemorySize*1024; "
            "free=[int64]$o.FreePhysicalMemory*1024} | ConvertTo-Json -Compress",
        )
        parsed = _parse_json_object(mem_out)
        if parsed and isinstance(parsed.get("total"), int) and isinstance(parsed.get("free"), int):
            total = parsed["total"]
            free = parsed["free"]
            memory = {
                "total_bytes": total,
                "free_bytes": free,
                "used_bytes": max(0, total - free),
            }
    except Exception as exc:
        log.debug("Nest Health Windows memory failed: %s", exc)

    try:
        disk_out = _run_windows_ps(
            transport,
            'Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | '
            "Select-Object DeviceID,Size,FreeSpace | ConvertTo-Json -Compress",
        )
        disks = _disks_from_win_json(disk_out)
    except Exception as exc:
        log.debug("Nest Health Windows disks failed: %s", exc)

    return {"cpu": cpu, "memory": memory, "disks": disks}


def _gather_resources_winrm(transport) -> dict[str, Any]:
    """Alias for tests / callers that still name the WinRM gather path."""
    return _gather_resources_windows(transport)


def _parse_int_line(text: str) -> int | None:
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            return int(line.split()[0])
        except ValueError:
            continue
    return None


def _parse_json_object(text: str) -> dict[str, Any] | None:
    val = _parse_json_value(text)
    return val if isinstance(val, dict) else None


def _parse_json_value(text: str) -> Any:
    raw = (text or "").strip()
    if not raw:
        return None
    # WinRM sometimes wraps or adds BOM / progress noise - take first JSON blob.
    for candidate in (
        raw,
        raw[raw.find("{") :] if "{" in raw else "",
        raw[raw.find("[") :] if "[" in raw else "",
    ):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def migrate_reachability_validator_settings() -> None:
    """One-time: copy nest_reachability enable/interval onto nest_health when unset."""
    stored = config.get().get("validators") or {}
    if not isinstance(stored, dict):
        return
    if "nest_health" in stored and isinstance(stored.get("nest_health"), dict):
        return
    reach = stored.get("nest_reachability")
    if not isinstance(reach, dict):
        return
    updated = dict(stored)
    updated["nest_health"] = {
        "enabled": bool(reach.get("enabled", True)),
        "interval_seconds": max(10, int(reach.get("interval_seconds") or 60)),
    }
    # Leave nest_reachability as stored; defaults will disable it for new installs.
    config.update_settings({"validators": updated})


__all__ = [
    "get_health",
    "get_snapshot",
    "migrate_reachability_validator_settings",
    "prune_removed_nests",
    "record_health",
    "run_as_validator",
    "run_health",
    "volume_storage_status",
]
