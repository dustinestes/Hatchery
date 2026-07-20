from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from lib import db

_HATCH_EVENT_RE = re.compile(
    r"^\[HATCH:(INFO|WARN|ERROR)\]"
    r"(?:\[(?!\d{4}-\d{2}-\d{2}T)([^\]]+)\])?"            # optional component (not a timestamp)
    r"(?:\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\])?"   # optional ISO timestamp
    r" (.+)$"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_session(clutch_file: str, clutch_name: str, nest: str = "local") -> str:
    """Insert a new hatch session and return its ID."""
    session_id = str(uuid.uuid4())
    conn = db.get_connection()
    try:
        conn.execute(
            """INSERT INTO hatch_sessions (id, nest, clutch_file, clutch_name, hatched_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, nest, clutch_file, clutch_name, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return session_id


def add_vm(
    session_id: str,
    vm_name: str,
    admin_username: str | None = None,
    admin_password: str | None = None,
) -> None:
    """Add a VM to a session in pending state, storing credentials for post-install automation."""
    conn = db.get_connection()
    try:
        conn.execute(
            """INSERT INTO hatch_vm_status
               (session_id, vm_name, status, admin_username, admin_password)
               VALUES (?, ?, 'pending', ?, ?)""",
            (session_id, vm_name, admin_username, admin_password),
        )
        conn.commit()
    finally:
        conn.close()


def set_vm_status(session_id: str, vm_name: str, status: str, error: str | None = None) -> None:
    """Update a VM's status, setting timestamps appropriate to the transition."""
    now = _now()
    conn = db.get_connection()
    try:
        if status == "hatching":
            conn.execute(
                """UPDATE hatch_vm_status SET status=?, started_at=?, error=?
                   WHERE session_id=? AND vm_name=?""",
                (status, now, error, session_id, vm_name),
            )
        elif status == "fledged":
            conn.execute(
                """UPDATE hatch_vm_status SET status=?, fledged_at=?, error=?
                   WHERE session_id=? AND vm_name=?""",
                (status, now, error, session_id, vm_name),
            )
            # All VMs fledged → record session completion time
            non_fledged = conn.execute(
                "SELECT COUNT(*) FROM hatch_vm_status WHERE session_id=? AND status != 'fledged'",
                (session_id,),
            ).fetchone()[0]
            if non_fledged == 0:
                conn.execute(
                    "UPDATE hatch_sessions SET completed_at=? WHERE id=?",
                    (now, session_id),
                )
        else:
            conn.execute(
                """UPDATE hatch_vm_status SET status=?, error=?
                   WHERE session_id=? AND vm_name=?""",
                (status, error, session_id, vm_name),
            )
        conn.commit()
    finally:
        conn.close()


def set_vm_uuid(session_id: str, vm_name: str, libvirt_uuid: str) -> None:
    """Store the hypervisor UUID for a VM — used as the authoritative identity for culled detection."""
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE hatch_vm_status SET libvirt_uuid=? WHERE session_id=? AND vm_name=?",
            (libvirt_uuid, session_id, vm_name),
        )
        conn.commit()
    finally:
        conn.close()


def update_vm_name(session_id: str, old_name: str, new_name: str) -> None:
    """Update a VM's stored name — called when a rename is detected via UUID lookup.

    Keeps hatch_vm_scripts in sync so (session_id, vm_name) remains a consistent key.
    """
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE hatch_vm_status SET vm_name=? WHERE session_id=? AND vm_name=?",
            (new_name, session_id, old_name),
        )
        conn.execute(
            "UPDATE hatch_vm_scripts SET vm_name=? WHERE session_id=? AND vm_name=?",
            (new_name, session_id, old_name),
        )
        conn.commit()
    finally:
        conn.close()


def get_vm_record(session_id: str, vm_name: str) -> dict | None:
    """Return the DB record for a specific VM in a session, or None if not found."""
    conn = db.get_connection()
    try:
        row = conn.execute(
            """SELECT vm_name, status, started_at, fledged_at, admin_username, admin_password
               FROM hatch_vm_status WHERE session_id=? AND vm_name=?""",
            (session_id, vm_name),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _compute_session_status(vms: list[dict]) -> str:
    if not vms:
        return "unknown"
    statuses = {v["status"] for v in vms}
    if "pending" in statuses or "hatching" in statuses or "provisioning" in statuses:
        return "in_progress"
    if "failed" in statuses or "blocked" in statuses:
        return "failed"
    if statuses == {"fledged"}:
        return "completed"
    if "culled" in statuses and not (statuses - {"fledged", "culled"}):
        return "degraded"
    return "unknown"


def archive_session(session_id: str) -> None:
    """Archive (dismiss) a session — removes it from the active Nests view."""
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE hatch_sessions SET archived_at=? WHERE id=?",
            (_now(), session_id),
        )
        conn.commit()
    finally:
        conn.close()


def archive_if_terminal(session_id: str) -> dict | None:
    """Archive the session if all VMs are in a terminal state (degraded or failed).

    Returns a summary dict with clutch_name, status, and vm counts if the session
    was archived this call; returns None if it was already archived or not terminal.
    """
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT clutch_name, archived_at FROM hatch_sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        if row is None or row["archived_at"] is not None:
            return None

        vms = conn.execute(
            "SELECT vm_name, status FROM hatch_vm_status WHERE session_id=?",
            (session_id,),
        ).fetchall()
        vm_dicts = [dict(v) for v in vms]
        status = _compute_session_status(vm_dicts)

        if status not in ("degraded", "failed"):
            return None

        conn.execute(
            "UPDATE hatch_sessions SET archived_at=? WHERE id=?",
            (_now(), session_id),
        )
        conn.commit()
        return {"clutch_name": row["clutch_name"], "status": status, "vms": vm_dicts}
    finally:
        conn.close()


def add_vm_scripts(session_id: str, vm_name: str, scripts: list) -> None:
    """Record the declared automation scripts for a VM at hatch time.

    Each AutomationScript is stored as a pending row in run_order. Inserted before the VM
    is created so the Nests panel can show the full script list immediately after hatching.
    """
    if not scripts:
        return
    conn = db.get_connection()
    try:
        for i, script in enumerate(scripts):
            conn.execute(
                """INSERT INTO hatch_vm_scripts
                   (session_id, vm_name, script_name, run_order, reboot_after, parameters, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
                (
                    session_id,
                    vm_name,
                    script.name,
                    i,
                    int(script.reboot_after),
                    json.dumps(p) if (p := getattr(script, "parameters", None)) else None,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_vm_scripts(session_id: str, vm_name: str) -> list[dict]:
    """Return all script rows for a VM in run_order, newest-first within the session."""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """SELECT script_name, run_order, reboot_after, status, exit_code, output,
                      parameters, started_at, completed_at
               FROM hatch_vm_scripts WHERE session_id=? AND vm_name=?
               ORDER BY run_order""",
            (session_id, vm_name),
        ).fetchall()
        result = []
        for r in rows:
            row = dict(r)
            row["parameters"] = json.loads(row["parameters"]) if row["parameters"] else {}
            result.append(row)
        return result
    finally:
        conn.close()


def set_script_status(
    session_id: str,
    vm_name: str,
    run_order: int,
    status: str,
    exit_code: int | None = None,
    output: str | None = None,
) -> None:
    """Update a single script row's status, exit code, output, and timestamps."""
    now = _now()
    conn = db.get_connection()
    try:
        if status == "running":
            conn.execute(
                """UPDATE hatch_vm_scripts SET status=?, started_at=?
                   WHERE session_id=? AND vm_name=? AND run_order=?""",
                (status, now, session_id, vm_name, run_order),
            )
        elif status in ("succeeded", "failed", "skipped"):
            conn.execute(
                """UPDATE hatch_vm_scripts
                   SET status=?, exit_code=?, output=?, completed_at=?
                   WHERE session_id=? AND vm_name=? AND run_order=?""",
                (status, exit_code, output, now, session_id, vm_name, run_order),
            )
        else:
            conn.execute(
                """UPDATE hatch_vm_scripts SET status=?
                   WHERE session_id=? AND vm_name=? AND run_order=?""",
                (status, session_id, vm_name, run_order),
            )
        conn.commit()
    finally:
        conn.close()


def reset_scripts_for_retry(session_id: str, vm_name: str) -> None:
    """Reset all non-succeeded scripts to pending so the provision thread can re-run them."""
    conn = db.get_connection()
    try:
        conn.execute(
            """UPDATE hatch_vm_scripts
               SET status='pending', exit_code=NULL, output=NULL,
                   started_at=NULL, completed_at=NULL
               WHERE session_id=? AND vm_name=? AND status IN ('failed', 'skipped', 'pending', 'running')""",
            (session_id, vm_name),
        )
        conn.commit()
    finally:
        conn.close()


def list_sessions(nest: str = "local") -> list[dict]:
    """Return active (non-archived) sessions for a nest, each with its VMs and computed status."""
    conn = db.get_connection()
    try:
        sessions = conn.execute(
            """SELECT id, nest, clutch_file, clutch_name, hatched_at, completed_at
               FROM hatch_sessions WHERE nest=? AND archived_at IS NULL
               ORDER BY hatched_at DESC, rowid DESC""",
            (nest,),
        ).fetchall()
        result = []
        for s in sessions:
            vms = conn.execute(
                """SELECT vm_name, status, libvirt_uuid, started_at, fledged_at, error
                   FROM hatch_vm_status WHERE session_id=? ORDER BY id""",
                (s["id"],),
            ).fetchall()
            vm_dicts = [dict(v) for v in vms]
            result.append(
                {
                    **dict(s),
                    "vms": vm_dicts,
                    "status": _compute_session_status(vm_dicts),
                }
            )
        return result
    finally:
        conn.close()


def parse_hatch_event_lines(output: str) -> list[dict]:
    """Extract [HATCH:TIER] tagged lines emitted by Write-HatchEvent from script output.

    Returns a list of dicts with keys: tier, component, received_at, message.
    component and received_at are None when omitted from the line.
    Lines that do not match the pattern are ignored.
    """
    events = []
    for line in output.splitlines():
        m = _HATCH_EVENT_RE.match(line.strip())
        if m:
            events.append(
                {
                    "tier": m.group(1),
                    "component": m.group(2),
                    "received_at": m.group(3),
                    "message": m.group(4),
                }
            )
    return events


def add_event(
    session_id: str,
    vm_name: str,
    context: str,
    tier: str,
    message: str,
    script_name: str | None = None,
    component: str | None = None,
    received_at: str | None = None,
) -> None:
    """Insert a single provisioning event for a VM.

    context:     'hatchery' for host-side lifecycle events, 'script' for Write-HatchEvent lines.
    tier:        'INFO', 'WARN', or 'ERROR'.
    script_name: the script file this event belongs to; None for session-level events.
    component:   within-script sub-component label from Write-HatchEvent -Component; None if omitted.
    received_at: ISO 8601 UTC timestamp from the guest; falls back to host time if None.
    """
    conn = db.get_connection()
    try:
        conn.execute(
            """INSERT INTO hatch_events
               (session_id, vm_name, context, tier, script_name, component, message, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, vm_name, context, tier, script_name, component, message, received_at or _now()),
        )
        conn.commit()
    finally:
        conn.close()


def get_events(session_id: str, vm_name: str) -> list[dict]:
    """Return all provisioning events for a VM in insertion order."""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """SELECT id, context, tier, script_name, component, message, received_at
               FROM hatch_events WHERE session_id=? AND vm_name=?
               ORDER BY id ASC""",
            (session_id, vm_name),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
