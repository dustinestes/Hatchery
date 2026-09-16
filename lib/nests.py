"""Nest connection registry — persist Nest definitions and build transport configs.

Registry lives in SQLite (``nests`` table). Provider selection for inventory /
lifecycle is #206; this module owns CRUD, validation, and Test Nest connection.

SSH identity fields (path, optional cert path, optional expiry) live on each Nest
row — not in Security Settings. Private key bytes are never stored (path refs only;
WinRM passwords are session/test-only until #110).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from lib import config
from lib import db as db_module
from lib import nest_key_expiry as nest_key_expiry_lib
from lib.nest_transport import (
    NestConnectionConfig,
    NestHealthCheckResult,
    NestSshConfig,
    NestWinrmConfig,
    get_nest_transport,
)

PROVIDER_TYPES = frozenset({"libvirt", "utm", "hyperv"})
LOCATIONS = frozenset({"local", "remote"})
TRANSPORTS = frozenset({"ssh", "winrm"})
KNOWN_HOSTS = frozenset({"default", "accept-new", "skip"})

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
    """Return all registered Nests, local first then by name."""
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
    conn = db_module.get_connection()
    try:
        row = conn.execute("SELECT * FROM nests WHERE id = ?", (nid,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def ensure_local_nest() -> dict:
    """Insert the default local libvirt Nest if missing; return it."""
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
                known_hosts, winrm_user, credential_ref, extra_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?)
            """,
            (LOCAL_NEST_ID, "Local", "libvirt", "local", now, now),
        )
        conn.commit()
    finally:
        conn.close()
    nest = get_nest(LOCAL_NEST_ID)
    assert nest is not None
    return nest


def normalize_nest(item: dict) -> dict:
    """Validate and normalize a single Nest dict (Settings row / test payload)."""
    return _normalize_one(item)


def parse_nests(raw: list | None) -> list[dict]:
    """Validate and normalize Nest dicts from Settings / API."""
    if not raw:
        raise ValueError("at least one Nest is required")
    if not isinstance(raw, list):
        raise ValueError("nests must be a list")

    out: list[dict] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    seen_endpoints: set[tuple[str, int, str]] = set()

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

        if nest["id"] != LOCAL_NEST_ID and nest["location"] == "local":
            raise ValueError(
                "only the built-in Nest id 'local' may use location 'local' — "
                "other Nests must be remote (even for localhost / WSL)"
            )

        if nest["location"] == "remote":
            host_key = str(nest["host"] or "").strip().casefold()
            port = int(nest["port"] or 0)
            transport = str(nest["transport"] or "ssh")
            endpoint = (host_key, port, transport)
            if endpoint in seen_endpoints:
                raise ValueError(
                    f"duplicate remote Nest endpoint: {nest['host']}:{port} via {transport} "
                    f"(same host/port/transport already registered)"
                )
            seen_endpoints.add(endpoint)

        out.append(nest)

    if LOCAL_NEST_ID not in seen_ids:
        raise ValueError(f"the built-in Nest id '{LOCAL_NEST_ID}' cannot be removed")

    local = next(n for n in out if n["id"] == LOCAL_NEST_ID)
    if local["location"] != "local":
        raise ValueError(f"Nest '{LOCAL_NEST_ID}' must have location 'local'")

    return out


def _normalize_one(item: dict) -> dict:
    nid = str(item.get("id") or "").strip() or new_id()
    if not _ID_RE.match(nid):
        raise ValueError(
            f"invalid Nest id {nid!r} — use letters, digits, ._- (max 64), start alphanumeric"
        )

    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("Nest name is required")

    provider = str(item.get("provider_type") or "libvirt").strip().lower()
    if provider not in PROVIDER_TYPES:
        raise ValueError(f"unsupported provider_type: {provider}")

    location = str(item.get("location") or "local").strip().lower()
    if location not in LOCATIONS:
        raise ValueError(f"location must be one of: {', '.join(sorted(LOCATIONS))}")

    # Non-builtin Nests are always remote (single local Nest = id "local").
    if nid != LOCAL_NEST_ID:
        location = "remote"

    transport_raw = item.get("transport")
    transport = str(transport_raw).strip().lower() if transport_raw else None
    host = _optional_str(item.get("host"))
    port = _optional_int(item.get("port"), label="port")
    ssh_user = _optional_str(item.get("ssh_user"))
    # identity_ref accepted as alias for older forms / drafts.
    identity_file = _optional_str(item.get("identity_file") or item.get("identity_ref"))
    cert_path = _optional_str(item.get("cert_path"))
    identity_expires_at = _parse_expires_at(item.get("identity_expires_at"), label=name)
    known_hosts = str(item.get("known_hosts") or "default").strip().lower()
    if known_hosts not in KNOWN_HOSTS:
        raise ValueError(f"known_hosts must be one of: {', '.join(sorted(KNOWN_HOSTS))}")
    winrm_user = _optional_str(item.get("winrm_user"))
    credential_ref = _optional_str(item.get("credential_ref"))
    extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}

    if location == "local":
        transport = None
        host = None
        port = None
        ssh_user = None
        identity_file = None
        cert_path = None
        identity_expires_at = None
        known_hosts = "default"
        winrm_user = None
        credential_ref = None
    else:
        if not transport:
            transport = "ssh"
        if transport not in TRANSPORTS:
            raise ValueError(f"transport must be one of: {', '.join(sorted(TRANSPORTS))}")
        if not host:
            raise ValueError(f"Nest '{name}' requires a host when remote")
        if transport == "ssh":
            if port is None:
                port = 22
            winrm_user = None
            credential_ref = None
        else:
            if port is None:
                port = 5985
            if not winrm_user:
                raise ValueError(f"Nest '{name}' requires a WinRM username when transport is winrm")
            # Password is never persisted here — credential_ref is a placeholder for #110.
            ssh_user = None
            identity_file = None
            cert_path = None
            identity_expires_at = None

    return {
        "id": nid,
        "name": name,
        "provider_type": provider,
        "location": location,
        "transport": transport,
        "host": host,
        "port": port,
        "ssh_user": ssh_user,
        "identity_file": identity_file,
        "cert_path": cert_path,
        "identity_expires_at": identity_expires_at,
        "known_hosts": known_hosts,
        "winrm_user": winrm_user,
        "credential_ref": credential_ref,
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
    """Replace the Nest registry with a validated list (Settings save)."""
    nests = parse_nests(raw)
    existing = {n["id"]: n for n in list_nests()}
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
                    known_hosts, winrm_user, credential_ref, extra_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    nest["known_hosts"] if nest["location"] == "remote" else None,
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
    return list_nests()


def resolve_identity_file(nest: dict) -> str | None:
    """Return the Nest's OpenSSH identity path (tilde expanded for transport)."""
    path = nest.get("identity_file")
    if not path:
        return None
    text = str(path).strip()
    return text or None


def to_connection_config(
    nest: dict,
    *,
    winrm_password: str | None = None,
) -> NestConnectionConfig:
    """Build a ``NestConnectionConfig`` for transport / cache helpers."""
    location = nest.get("location") or "local"
    if location == "local":
        return NestConnectionConfig(location="local", extra=dict(nest.get("extra") or {}))

    transport = nest.get("transport") or "ssh"
    if transport == "ssh":
        identity = resolve_identity_file(nest)
        if identity and identity.startswith("~"):
            identity = str(Path(identity).expanduser())
        return NestConnectionConfig(
            location="remote",
            transport="ssh",
            ssh=NestSshConfig(
                host=str(nest["host"]),
                user=nest.get("ssh_user"),
                port=int(nest.get("port") or 22),
                identity_file=identity,
                known_hosts=nest.get("known_hosts") or "default",  # type: ignore[arg-type]
            ),
            extra=dict(nest.get("extra") or {}),
        )

    password = winrm_password if winrm_password is not None else ""
    return NestConnectionConfig(
        location="remote",
        transport="winrm",
        winrm=NestWinrmConfig(
            host=str(nest["host"]),
            username=str(nest.get("winrm_user") or ""),
            password=password,
            port=int(nest.get("port") or 5985),
        ),
        extra=dict(nest.get("extra") or {}),
    )


def test_connection(
    nest: dict,
    *,
    winrm_password: str | None = None,
) -> dict:
    """Run Test Nest connection; return ``{ok, message}`` for the UI."""
    nest = _normalize_one(nest)
    if nest["location"] == "local":
        return {
            "ok": True,
            "message": "Local Nest — no remote transport (inventory uses the Nest provider).",
        }

    if nest["transport"] == "winrm" and not (winrm_password or "").strip():
        return {
            "ok": False,
            "message": "WinRM password is required for Test Nest connection (not stored — #110).",
        }

    try:
        connection = to_connection_config(nest, winrm_password=winrm_password)
        transport = get_nest_transport(connection)
    except (ValueError, TypeError) as exc:
        return {"ok": False, "message": str(exc)}

    if transport is None:
        return {"ok": True, "message": "Local Nest — no remote transport."}

    result: NestHealthCheckResult = transport.test_connection()
    return {"ok": result.ok, "message": result.detail}


def identities_for_expiry() -> list[nest_key_expiry_lib.NestSshIdentity]:
    """Build expiry-check identities from Nest rows (SSH path / cert / expiry)."""
    out: list[nest_key_expiry_lib.NestSshIdentity] = []
    for nest in list_nests():
        if nest.get("location") != "remote":
            continue
        if (nest.get("transport") or "ssh") != "ssh":
            continue
        path = nest.get("identity_file")
        cert = nest.get("cert_path")
        expires_raw = nest.get("identity_expires_at")
        if not path and not cert and not expires_raw:
            continue
        expires_at = None
        if expires_raw:
            parsed = nest_key_expiry_lib.parse_identities(
                [{"id": nest["id"], "expires_at": expires_raw}]
            )
            if parsed:
                expires_at = parsed[0].expires_at
        out.append(
            nest_key_expiry_lib.NestSshIdentity(
                id=str(nest["id"]),
                label=str(nest.get("name") or nest["id"]),
                identity_file=path,
                cert_path=cert,
                expires_at=expires_at,
                expires_source="manual",
            )
        )
    return out


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
        config.save({**cfg, "nest_ssh_identities": []})
        return True
    return changed
