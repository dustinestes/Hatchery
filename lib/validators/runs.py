"""Persist validator run history (Notifications → Validators)."""

from __future__ import annotations

from datetime import datetime, timezone

from lib import alerts as alerts_lib
from lib import db
from lib.validators import settings as validator_settings


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_run(
    *,
    validator_id: str,
    status: str,
    message: str,
    trigger: str = "schedule",
    tier: str | None = None,
    detail: str | None = None,
    nest_id: str | None = None,
    findings_count: int = 0,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> int:
    """Insert a run row and trim retention. Returns new id."""
    started = started_at or _now()
    finished = finished_at or _now()
    status_norm = status if status in ("ok", "error") else "error"
    tier_norm = alerts_lib.normalize_tier(tier or ("alert" if status_norm == "error" else "info"))
    trigger_norm = trigger if trigger in ("schedule", "manual", "connection") else "schedule"
    conn = db.get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO validator_runs (
                validator_id, started_at, finished_at, status, tier, trigger,
                message, detail, nest_id, findings_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                validator_id,
                started,
                finished,
                status_norm,
                tier_norm,
                trigger_norm,
                message,
                detail,
                nest_id,
                int(findings_count),
            ),
        )
        row_id = int(cur.lastrowid)
        _trim(conn, validator_id)
        conn.commit()
        return row_id
    finally:
        conn.close()


def _trim(conn, validator_id: str) -> None:
    limit = validator_settings.get_run_retention()
    rows = conn.execute(
        """
        SELECT id FROM validator_runs
        WHERE validator_id = ?
        ORDER BY id DESC
        """,
        (validator_id,),
    ).fetchall()
    if len(rows) <= limit:
        return
    drop_ids = [r["id"] for r in rows[limit:]]
    conn.executemany("DELETE FROM validator_runs WHERE id = ?", [(i,) for i in drop_ids])


def list_runs(
    *,
    limit: int = 100,
    validator_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    conn = db.get_connection()
    try:
        clauses: list[str] = []
        params: list = []
        if validator_id:
            clauses.append("validator_id = ?")
            params.append(validator_id)
        if status in ("ok", "error"):
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(500, int(limit))))
        rows = conn.execute(
            f"""
            SELECT * FROM validator_runs
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def latest_by_validator() -> dict[str, dict]:
    """Map validator_id → newest run row."""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT r.* FROM validator_runs r
            INNER JOIN (
                SELECT validator_id, MAX(id) AS max_id
                FROM validator_runs
                GROUP BY validator_id
            ) t ON r.id = t.max_id
            """
        ).fetchall()
        return {r["validator_id"]: dict(r) for r in rows}
    finally:
        conn.close()
