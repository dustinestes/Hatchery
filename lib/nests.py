"""Nest connection registry - persist Nest definitions for Local Nest ops.

Registry lives in SQLite (``nests`` table). Provider selection for inventory /
lifecycle is #206; this module owns CRUD, validation, and Test Nest connection.

Free HEAD is Local Nest only (#620). Remote Nest product (Nest SSH / WinRM)
was removed from free; Enterprise Remote Nest is Nest Agent (#345). Schema
columns for remote fields may remain dormant for DB compatibility.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from lib import alerts as alerts_lib
from lib import config
from lib import db as db_module
from lib import nest_key_expiry as nest_key_expiry_lib
from lib.nest_types import NestConnectionConfig

PROVIDER_TYPES = frozenset({"libvirt", "utm", "hyperv"})
LOCATIONS = frozenset({"local"})
_REMOTE_UNAVAILABLE = (
    "Remote Nests are not available in Hatchery free (#620). "
    "Use a Local Nest on this Controller, or Hatchery Enterprise (Nest Agent)."
)

LOCAL_NEST_ID = "local"
_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(row) -> dict:
    # Legacy drafts may still have identity_ref until migrate copies path-like values.
    identity_file = row["identity_file"] if "identity_file" in row.keys() else None
    if not identity_file and "identity_ref" in row.keys():
        identity_file = row["identity_ref"]
    remoting_identity_id = None
    if "remoting_identity_id" in row.keys():
        remoting_identity_id = row["remoting_identity_id"]
    return {
        "id": row["id"],
        "name": row["name"],
        "provider_type": row["provider_type"],
        "location": row["location"],
        "transport": row["transport"],
        "host": row["host"],
        "port": row["port"],
        "ssh_user": row["ssh_user"],
        "identity_file": identity_file,
        "cert_path": row["cert_path"] if "cert_path" in row.keys() else None,
        "identity_expires_at": row["identity_expires_at"]
        if "identity_expires_at" in row.keys()
        else None,
        "remoting_identity_id": remoting_identity_id,
        "known_hosts": row["known_hosts"] or "default",
        "winrm_user": row["winrm_user"],
        "credential_ref": row["credential_ref"],
        "extra": _parse_extra(row["extra_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _parse_extra(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def list_nests() -> list[dict]:
    """Return all registered Nests, local first then by name.

    Returns an empty list when the Controller database is not open yet
    (inspect against a data dir with no ``hatchery.db``).
    """
    if not db_module.is_initialized():
        return []
    conn = db_module.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM nests
            ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END, name COLLATE NOCASE, id
            """,
            (LOCAL_NEST_ID,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_nest(nest_id: str) -> dict | None:
    """Return one Nest by id, or None."""
    nid = str(nest_id or "").strip()
    if not nid:
        return None
    if not db_module.is_initialized():
        return None
    conn = db_module.get_connection()
    try:
        row = conn.execute("SELECT * FROM nests WHERE id = ?", (nid,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def update_nest_extra(nest_id: str, patch: dict) -> dict:
    """Merge ``patch`` into Nest ``extra_json``; values of ``None`` delete keys.

    Returns the updated Nest row.
    """
    nid = str(nest_id or "").strip()
    nest = get_nest(nid)
    if nest is None:
        raise ValueError(f"Unknown Nest id: {nid}")
    if not isinstance(patch, dict):
        raise ValueError("extra patch must be a dict")
    extra = dict(nest.get("extra") or {})
    for key, value in patch.items():
        if value is None:
            extra.pop(key, None)
        else:
            extra[key] = value
    now = _now()
    payload = json.dumps(extra) if extra else None
    conn = db_module.get_connection()
    try:
        conn.execute(
            "UPDATE nests SET extra_json = ?, updated_at = ? WHERE id = ?",
            (payload, now, nid),
        )
        conn.commit()
    finally:
        conn.close()
    updated = get_nest(nid)
    assert updated is not None
    return updated


def ensure_local_nest() -> dict:
    """Insert the default local libvirt Nest if missing; return it.

    Opt-in only (CLI ``--nest-local``, env ``HATCHERY_NEST_LOCAL``,
    or Settings Add Local Nest). Fresh Controllers start with an empty registry
    (ADR-0014 / #266). Idempotent: no-op when id ``local`` already exists.
    """
    existing = get_nest(LOCAL_NEST_ID)
    if existing:
        return existing
    now = _now()
    conn = db_module.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO nests (
                id, name, provider_type, location, transport,
                host, port, ssh_user, identity_file, cert_path, identity_expires_at,
                remoting_identity_id, known_hosts, winrm_user, credential_ref,
                extra_json, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?
            )
            """,
            (LOCAL_NEST_ID, "Local", "libvirt", "local", now, now),
        )
        conn.commit()
    finally:
        conn.close()
    nest = get_nest(LOCAL_NEST_ID)
    assert nest is not None
    return nest


def default_nest_id() -> str | None:
    """Return the sole registered Nest id, or None if zero or many Nests."""
    nests = list_nests()
    if len(nests) == 1:
        return nests[0]["id"]
    return None


def normalize_nest(item: dict) -> dict:
    """Validate and normalize a single Nest dict (Settings row / test payload)."""
    return _normalize_one(item)


def parse_nests(raw: list | None) -> list[dict]:
    """Validate and normalize Nest dicts from Settings / API.

    Empty registry is allowed (Controller-only / ADR-0014). Local Nest id
    ``local`` is optional; when present it must use ``location=local``.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("nests must be a list")
    if not raw:
        return []

    out: list[dict] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()

    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each Nest must be an object")
        nest = _normalize_one(item)
        if nest["id"] in seen_ids:
            raise ValueError(f"duplicate Nest id: {nest['id']}")
        seen_ids.add(nest["id"])

        name_key = nest["name"].casefold()
        if name_key in seen_names:
            raise ValueError(f"duplicate Nest name: {nest['name']!r} (names must be unique)")
        seen_names.add(name_key)

        if nest["id"] != LOCAL_NEST_ID:
            raise ValueError(
                f"Nest id {nest['id']!r} is not allowed on free HEAD - "
                f"only Nest id '{LOCAL_NEST_ID}' (Local) may be registered (#620)"
            )

        out.append(nest)

    if LOCAL_NEST_ID in seen_ids:
        local = next(n for n in out if n["id"] == LOCAL_NEST_ID)
        if local["location"] != "local":
            raise ValueError(f"Nest '{LOCAL_NEST_ID}' must have location 'local'")

    return out


def _normalize_one(item: dict) -> dict:
    nid = str(item.get("id") or "").strip() or new_id()
    if not _ID_RE.match(nid):
        raise ValueError(
            f"invalid Nest id {nid!r} - use letters, digits, ._- (max 64), start alphanumeric"
        )

    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("Nest name is required")

    provider = str(item.get("provider_type") or "libvirt").strip().lower()
    if provider not in PROVIDER_TYPES:
        raise ValueError(f"unsupported provider_type: {provider}")

    location = str(item.get("location") or "local").strip().lower()
    if location == "remote" or location not in LOCATIONS:
        raise ValueError(_REMOTE_UNAVAILABLE)

    if nid != LOCAL_NEST_ID:
        raise ValueError(
            f"Nest id {nid!r} is not allowed on free HEAD - "
            f"only Nest id '{LOCAL_NEST_ID}' (Local) may be registered (#620)"
        )

    extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}

    return {
        "id": nid,
        "name": name,
        "provider_type": provider,
        "location": "local",
        "transport": None,
        "host": None,
        "port": None,
        "ssh_user": None,
        "identity_file": None,
        "cert_path": None,
        "identity_expires_at": None,
        "remoting_identity_id": None,
        "known_hosts": "default",
        "winrm_user": None,
        "credential_ref": None,
        "extra": extra,
        "created_at": _optional_str(item.get("created_at")),
        "updated_at": _optional_str(item.get("updated_at")),
    }


def _parse_expires_at(value: object, *, label: str) -> str | None:
    """Normalize optional Nest identity expiry to ISO-8601 UTC (date or datetime)."""
    text = str(value or "").strip()
    if not text:
        return None
    # HTML date input → YYYY-MM-DD
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return f"{text}T00:00:00+00:00"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"Nest '{label}' identity expiry must be YYYY-MM-DD or ISO-8601 datetime"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _optional_str(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_int(value: object, *, label: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if n < 1 or n > 65535:
        raise ValueError(f"{label} must be between 1 and 65535")
    return n


def replace_nests(raw: list | None) -> list[dict]:
    """Replace the Nest registry with a validated list (Settings save).

    Removed Nest ids resolve Nest-scoped Alerts (history retained) and are
    dropped from the reachability snapshot (#275).
    """
    nests = parse_nests(raw)
    existing = {n["id"]: n for n in list_nests()}
    kept_ids = {n["id"] for n in nests}
    removed_ids = set(existing) - kept_ids
    now = _now()
    conn = db_module.get_connection()
    try:
        conn.execute("DELETE FROM nests")
        for nest in nests:
            created = (
                (existing.get(nest["id"]) or {}).get("created_at") or nest.get("created_at") or now
            )
            conn.execute(
                """
                INSERT INTO nests (
                    id, name, provider_type, location, transport,
                    host, port, ssh_user, identity_file, cert_path, identity_expires_at,
                    remoting_identity_id, known_hosts, winrm_user, credential_ref,
                    extra_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    nest["id"],
                    nest["name"],
                    nest["provider_type"],
                    nest["location"],
                    nest["transport"],
                    nest["host"],
                    nest["port"],
                    nest["ssh_user"],
                    nest["identity_file"],
                    nest["cert_path"],
                    nest["identity_expires_at"],
                    nest.get("remoting_identity_id"),
                    None,
                    nest["winrm_user"],
                    nest["credential_ref"],
                    json.dumps(nest["extra"]) if nest["extra"] else None,
                    created,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    if removed_ids:
        from lib import nest_health as nest_health_lib

        for nest_id in removed_ids:
            alerts_lib.resolve_alerts_for_nest_id(nest_id)
        from lib import nest_reachability as nest_reachability_lib

        nest_reachability_lib.prune_removed_nests(kept_ids)
        nest_health_lib.prune_removed_nests(kept_ids)
        from lib import nest_cache_sync as nest_cache_sync_lib
        from lib import nest_events as nest_events_lib

        nest_cache_sync_lib.prune_removed_nests(kept_ids)
        nest_events_lib.prune_removed_nests(kept_ids)
    return list_nests()


def to_connection_config(
    nest: dict,
    *,
    winrm_password: str | None = None,
) -> NestConnectionConfig:
    """Build a Local Nest ``NestConnectionConfig`` for cache helpers (#620)."""
    del winrm_password  # Remote WinRM session creds removed with Nest transport.
    location = nest.get("location") or "local"
    if location != "local":
        raise ValueError(_REMOTE_UNAVAILABLE)
    return NestConnectionConfig(location="local", extra=dict(nest.get("extra") or {}))


def _apply_manual_reachability(nest: dict, result, *, registered: bool) -> None:
    """Persist Test Nest connection reachability for registered Nests only (#283).

    Draft / unsaved rows stay out of the snapshot and Alerts. Saved Nests update
    the snapshot so UI surfaces can refresh immediately; success resolves any open
    reachability Alert. Failures do not open Alerts — ``nest_reachability`` owns that.
    """
    if not registered:
        return
    from lib import nest_reachability as nr

    nr.record_probe(nest, result)
    if result.ok:
        nr.sync_alert_for_probe(nest, result)


def test_connection(
    nest: dict,
    *,
    winrm_password: str | None = None,
) -> dict:
    """Run Test Nest connection; return ``{ok, message}`` for the UI.

    Registered Nests use Nest Health gather (#538). Draft / unsaved rows keep a
    reachability + capability probe without writing Nest Health history.
    Snapshot / Alert side effects apply only to Nests already in the registry
    (#283); the inline message always reflects the probe.
    """
    from lib import nest_health as nest_health_lib
    from lib import nest_reachability as nr
    from lib import requirements as req_lib

    try:
        nest = _normalize_one(nest)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    registered = get_nest(nest["id"]) is not None

    if registered:
        health = nest_health_lib.run_health(
            nest,
            winrm_password=winrm_password,
            persist=True,
            sync_alerts=True,
        )
        gate = health.get("gate") or {}
        reach_msg = gate.get("detail") or ("OK" if health.get("ok") else "Unreachable")
        if not health.get("ok"):
            return {"ok": False, "message": reach_msg}
        missing_prereq = [
            p["name"] for p in (health.get("prerequisites") or []) if not p.get("present")
        ]
        if missing_prereq:
            names = ", ".join(missing_prereq)
            return {
                "ok": False,
                "message": f"{reach_msg} Missing Nest tools: {names}.",
            }
        return {"ok": True, "message": f"{reach_msg} Nest Health OK."}

    # Draft row: reachability + capability without Nest Health persistence.
    # Nest Events are Nest-registry keyed; drafts do not write transport lines (#611).
    # Registered Test Nest connection writes via Nest Health (topic=health).
    local_result = nr.probe_nest(nest)
    reach_msg = local_result.detail or "Local Nest - co-located with the Controller."

    missing = req_lib.missing(req_lib.check_nest(nest, winrm_password=winrm_password))
    if missing:
        names = ", ".join(r.name for r in missing)
        return {
            "ok": False,
            "message": f"{reach_msg} Missing Nest tools: {names}.",
        }
    return {"ok": True, "message": f"{reach_msg} Nest capability OK."}


def identities_for_expiry() -> list[nest_key_expiry_lib.NestSshIdentity]:
    """Legacy Nest-row SSH identity feed - empty on free HEAD (#620).

    Remoting catalog expiry remains via ``remoting_identities.identities_for_expiry``.
    """
    return []


def migrate_legacy_identity_bindings() -> int:
    """No-op on free HEAD (#620). Remote Nest identity migration removed with Nest SSH."""
    return 0


def migrate_legacy_ssh_identities() -> bool:
    """Apply Security ``nest_ssh_identities`` onto matching Nest rows once; clear Settings list.

    Matches when a Nest ``identity_file`` equals an identity id (legacy ref).
    Returns True if Settings changed.
    """
    raw = list(config.nest_ssh_identities() or [])
    if not raw:
        return False

    identities = nest_key_expiry_lib.parse_identities(raw)
    by_id = {i.id: i for i in identities}
    nests = list_nests()
    changed = False
    updated: list[dict] = []

    for nest in nests:
        row = dict(nest)
        ref = row.get("identity_file")
        if ref and ref in by_id:
            ident = by_id[ref]
            row["identity_file"] = ident.identity_file or ref
            if ident.cert_path:
                row["cert_path"] = ident.cert_path
            if ident.expires_at is not None:
                row["identity_expires_at"] = ident.expires_at.isoformat()
            changed = True
        updated.append(row)

    if changed:
        replace_nests(updated)

    cfg = config.get()
    if cfg.get("nest_ssh_identities"):
        config.update_settings({"nest_ssh_identities": []})
        return True
    return changed
