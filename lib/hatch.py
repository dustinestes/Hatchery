from __future__ import annotations

import uuid
from datetime import datetime, timezone

from lib import db


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


def add_vm(session_id: str, vm_name: str) -> None:
    """Add a VM to a session in pending state."""
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO hatch_vm_status (session_id, vm_name, status) VALUES (?, ?, 'pending')",
            (session_id, vm_name),
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
    """Update a VM's stored name — called when a rename is detected via UUID lookup."""
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE hatch_vm_status SET vm_name=? WHERE session_id=? AND vm_name=?",
            (new_name, session_id, old_name),
        )
        conn.commit()
    finally:
        conn.close()


def _compute_session_status(vms: list[dict]) -> str:
    if not vms:
        return "unknown"
    statuses = {v["status"] for v in vms}
    if "pending" in statuses or "hatching" in statuses:
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
