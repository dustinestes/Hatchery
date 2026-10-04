"""Controller remoting identity catalog (ADR-0030 / #522).

Path references only - never private key bytes in SQLite. Shared by Nest and
Guest transport planes; binding stays explicit on Nest rows / Clutch authorize.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from lib import config
from lib import db
from lib import nest_key_expiry as nest_key_expiry_lib

HATCHERY_IDENTITY_ID = "hatchery"
IdentityKind = Literal["hatchery", "path"]

_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


class RemotingIdentityError(RuntimeError):
    """Raised when a remoting identity cannot be created or resolved."""


@dataclass(frozen=True)
class RemotingIdentity:
    id: str
    name: str
    kind: IdentityKind
    identity_file: str
    pubkey: str | None = None
    cert_path: str | None = None
    identity_expires_at: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def resolved_path(self) -> Path:
        """Absolute path to the private key on the Controller."""
        return resolve_identity_path(self.identity_file)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def remoting_dir() -> Path:
    """Directory for Hatchery-managed remoting keys under ``data_dir``."""
    path = Path(config.data_dir()) / "remoting"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_identity_path(identity_file: str) -> Path:
    """Expand ``~`` and relative paths against ``data_dir``."""
    raw = (identity_file or "").strip()
    if not raw:
        raise RemotingIdentityError("identity_file is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path(config.data_dir()) / path
    return path.resolve()


def _validate_id(identity_id: str) -> str:
    tid = (identity_id or "").strip()
    if not tid or not _ID_RE.match(tid):
        raise RemotingIdentityError(
            "identity id must be 1-64 chars: alphanumeric, '.', '_', '-' "
            "(must start with alphanumeric)"
        )
    return tid


def _read_pubkey_file(priv: Path) -> str | None:
    pub = Path(str(priv) + ".pub")
    if not pub.is_file():
        return None
    text = pub.read_text(encoding="utf-8", errors="replace").strip()
    return text or None


def _row_to_identity(row: Any) -> RemotingIdentity:
    return RemotingIdentity(
        id=str(row["id"]),
        name=str(row["name"]),
        kind=str(row["kind"]),  # type: ignore[arg-type]
        identity_file=str(row["identity_file"]),
        pubkey=row["pubkey"],
        cert_path=row["cert_path"],
        identity_expires_at=row["identity_expires_at"],
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


def list_identities() -> list[RemotingIdentity]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM remoting_identities ORDER BY kind ASC, id ASC"
        ).fetchall()
        return [_row_to_identity(r) for r in rows]
    finally:
        conn.close()


def get_identity(identity_id: str) -> RemotingIdentity | None:
    tid = (identity_id or "").strip()
    if not tid:
        return None
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT * FROM remoting_identities WHERE id = ?", (tid,)).fetchone()
        return _row_to_identity(row) if row else None
    finally:
        conn.close()


def resolve(identity_id: str) -> RemotingIdentity:
    """Return identity or raise. Ensures Hatchery-managed key exists when id is hatchery."""
    tid = (identity_id or "").strip()
    if tid == HATCHERY_IDENTITY_ID:
        ensure_hatchery_identity()
    ident = get_identity(tid)
    if ident is None:
        raise RemotingIdentityError(f"unknown remoting identity: {tid!r}")
    return ident


def identity_private_path(identity_id: str) -> Path:
    """Resolve catalog id to absolute private key path."""
    return resolve(identity_id).resolved_path()


def _upsert(
    *,
    identity_id: str,
    name: str,
    kind: IdentityKind,
    identity_file: str,
    pubkey: str | None,
    cert_path: str | None,
    identity_expires_at: str | None,
) -> RemotingIdentity:
    now = _utc_now()
    conn = db.get_connection()
    try:
        existing = conn.execute(
            "SELECT created_at FROM remoting_identities WHERE id = ?", (identity_id,)
        ).fetchone()
        created = str(existing["created_at"]) if existing else now
        conn.execute(
            """
            INSERT INTO remoting_identities (
                id, name, kind, identity_file, pubkey, cert_path,
                identity_expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                kind = excluded.kind,
                identity_file = excluded.identity_file,
                pubkey = excluded.pubkey,
                cert_path = excluded.cert_path,
                identity_expires_at = excluded.identity_expires_at,
                updated_at = excluded.updated_at
            """,
            (
                identity_id,
                name,
                kind,
                identity_file,
                pubkey,
                cert_path,
                identity_expires_at,
                created,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    ident = get_identity(identity_id)
    assert ident is not None
    return ident


def _run_ssh_keygen(priv: Path, *, comment: str) -> None:
    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen is None:
        raise RemotingIdentityError("`ssh-keygen` not found on the Controller PATH")
    priv.parent.mkdir(parents=True, exist_ok=True)
    if priv.exists():
        priv.unlink()
    pub = Path(str(priv) + ".pub")
    if pub.exists():
        pub.unlink()
    try:
        subprocess.run(
            [
                ssh_keygen,
                "-t",
                "ed25519",
                "-f",
                str(priv),
                "-N",
                "",
                "-C",
                comment,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RemotingIdentityError(f"ssh-keygen failed: {err}") from exc
    os.chmod(priv, stat.S_IRUSR | stat.S_IWUSR)


def ensure_hatchery_identity(*, rotate: bool = False) -> RemotingIdentity:
    """Create or refresh the Hatchery-managed remoting key under ``data_dir/remoting``."""
    rel = "remoting/hatchery_ed25519"
    priv = remoting_dir() / "hatchery_ed25519"
    existing = get_identity(HATCHERY_IDENTITY_ID)
    if existing and priv.is_file() and not rotate:
        pubkey = existing.pubkey or _read_pubkey_file(priv)
        if pubkey and pubkey != existing.pubkey:
            return _upsert(
                identity_id=HATCHERY_IDENTITY_ID,
                name=existing.name or "Hatchery",
                kind="hatchery",
                identity_file=rel,
                pubkey=pubkey,
                cert_path=existing.cert_path,
                identity_expires_at=existing.identity_expires_at,
            )
        return existing

    _run_ssh_keygen(priv, comment="hatchery-remoting")
    pubkey = _read_pubkey_file(priv)
    return _upsert(
        identity_id=HATCHERY_IDENTITY_ID,
        name="Hatchery",
        kind="hatchery",
        identity_file=rel,
        pubkey=pubkey,
        cert_path=None,
        identity_expires_at=None,
    )


def add_path_identity(
    *,
    identity_id: str,
    identity_file: str,
    name: str | None = None,
    cert_path: str | None = None,
    identity_expires_at: str | None = None,
) -> RemotingIdentity:
    """Register an operator-supplied private key path."""
    tid = _validate_id(identity_id)
    if tid == HATCHERY_IDENTITY_ID:
        raise RemotingIdentityError(
            f"id {HATCHERY_IDENTITY_ID!r} is reserved for the Hatchery-managed key; "
            "use `remoting-identity generate` / `rotate`"
        )
    path = resolve_identity_path(identity_file)
    if not path.is_file():
        raise RemotingIdentityError(f"identity file not found: {path}")
    # Store expanded absolute path for path kind (stable across cwd).
    stored = str(path)
    pubkey = _read_pubkey_file(path)
    label = (name or "").strip() or tid
    cert = None
    if cert_path and str(cert_path).strip():
        cpath = resolve_identity_path(str(cert_path).strip())
        if not cpath.is_file():
            raise RemotingIdentityError(f"cert file not found: {cpath}")
        cert = str(cpath)
    expires = (identity_expires_at or "").strip() or None
    if expires:
        parsed = nest_key_expiry_lib.parse_identities([{"id": tid, "expires_at": expires}])
        if not parsed or parsed[0].expires_at is None:
            raise RemotingIdentityError(f"invalid identity_expires_at: {expires!r}")
        expires = parsed[0].expires_at.isoformat()
    return _upsert(
        identity_id=tid,
        name=label,
        kind="path",
        identity_file=stored,
        pubkey=pubkey,
        cert_path=cert,
        identity_expires_at=expires,
    )


def remove_identity(identity_id: str, *, delete_files: bool = False) -> None:
    """Remove a catalog row. Hatchery-managed files deleted only when ``delete_files``."""
    tid = (identity_id or "").strip()
    ident = get_identity(tid)
    if ident is None:
        raise RemotingIdentityError(f"unknown remoting identity: {tid!r}")
    if ident.kind == "hatchery" and not delete_files:
        raise RemotingIdentityError(
            "refusing to remove Hatchery-managed identity without --delete-files "
            "(use rotate to replace the key, or pass --delete-files to drop the row+files)"
        )
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM remoting_identities WHERE id = ?", (tid,))
        conn.commit()
    finally:
        conn.close()
    if delete_files and ident.kind == "hatchery":
        priv = remoting_dir() / "hatchery_ed25519"
        pub = Path(str(priv) + ".pub")
        priv.unlink(missing_ok=True)
        pub.unlink(missing_ok=True)


def rotate_hatchery_identity() -> RemotingIdentity:
    """Generate a new Hatchery-managed keypair and update the catalog row."""
    return ensure_hatchery_identity(rotate=True)


@dataclass(frozen=True)
class IdentityCheck:
    """Result of checking one remoting identity on disk."""

    identity_id: str
    ok: bool
    detail: str


def check_identity(ident: RemotingIdentity) -> IdentityCheck:
    """Validate private key path exists, is a file, and is not world-readable."""
    try:
        path = ident.resolved_path()
    except RemotingIdentityError as exc:
        return IdentityCheck(ident.id, False, str(exc))
    if not path.is_file():
        return IdentityCheck(ident.id, False, f"identity file missing: {path}")
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        return IdentityCheck(ident.id, False, f"cannot stat identity file: {exc}")
    # Unix permission bits are not meaningful on Windows Controllers.
    if os.name == "posix" and mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
        return IdentityCheck(
            ident.id,
            False,
            f"identity file is group/world accessible: {path} (expected 0600)",
        )
    if not ident.pubkey and not _read_pubkey_file(path):
        return IdentityCheck(
            ident.id,
            False,
            f"public key missing beside private key ({path}.pub)",
        )
    return IdentityCheck(ident.id, True, "ok")


def check_all_identities() -> list[IdentityCheck]:
    return [check_identity(i) for i in list_identities()]


def identities_for_expiry() -> list[nest_key_expiry_lib.NestSshIdentity]:
    """Catalog identities with path/cert/expiry for the Nest key expiry alerter shape."""
    out: list[nest_key_expiry_lib.NestSshIdentity] = []
    for ident in list_identities():
        expires_at = None
        if ident.identity_expires_at:
            parsed = nest_key_expiry_lib.parse_identities(
                [{"id": ident.id, "expires_at": ident.identity_expires_at}]
            )
            if parsed:
                expires_at = parsed[0].expires_at
        out.append(
            nest_key_expiry_lib.NestSshIdentity(
                id=f"remoting:{ident.id}",
                label=ident.name,
                identity_file=str(ident.resolved_path()),
                cert_path=ident.cert_path,
                expires_at=expires_at,
                expires_source="manual",
            )
        )
    return out


def to_dict(ident: RemotingIdentity) -> dict[str, Any]:
    return {
        "id": ident.id,
        "name": ident.name,
        "kind": ident.kind,
        "identity_file": ident.identity_file,
        "resolved_path": str(ident.resolved_path()) if ident.identity_file else None,
        "pubkey": ident.pubkey,
        "cert_path": ident.cert_path,
        "identity_expires_at": ident.identity_expires_at,
        "created_at": ident.created_at,
        "updated_at": ident.updated_at,
    }
