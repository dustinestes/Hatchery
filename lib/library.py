"""Library connections and domain bindings - list, test, and pull into the operator cache.

``path`` (local or mounted share), ``https`` (single relative file), ``api``
(pluggable catalog providers - #255), and ``forge`` (pluggable git forge
providers - #307) are supported. Classic ``type: git`` clone cache was removed
(#406 / ADR-0020); leftover rows refuse test/list/pull/tip.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from fnmatch import fnmatch
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lib.import_files import SCRIPT_EXTENSIONS

CONNECTION_TYPES = frozenset({"path", "https", "api", "forge"})
CONNECTION_KINDS = frozenset({"scripts", "clutches", "media", "packages"})
MEDIA_EXTENSIONS = frozenset({".iso"})
MEDIA_TARGETS = frozenset({"iso", "virtio"})
CLUTCH_EXTENSIONS = frozenset({".yaml"})
_SAMPLE_LIMIT = 5
_SCRIPT_PULL_DEST = "automation/scripts"
_CLUTCH_PULL_DEST = "clutches"
_LEGACY_GIT_CACHE_SUBDIR = "library/git"
_LEGACY_GIT_REMOVED_MSG = (
    "Library connection type 'git' was removed; recreate as forge or path (#406 / ADR-0020)"
)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def min_expires_at() -> date:
    """Earliest allowed token expiry calendar day (tomorrow, local date)."""
    return date.today() + timedelta(days=1)


def parse_expires_at(raw: object, *, label: str, enforce_future: bool = True) -> str | None:
    """Parse an optional calendar day (YYYY-MM-DD).

    Empty means no expiry tracked. When set and ``enforce_future`` is true
    (Settings save), the day must be on or after tomorrow.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        expires = date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(
            f"connection '{label}' has an invalid expiry date (use YYYY-MM-DD)"
        ) from exc
    if enforce_future:
        earliest = min_expires_at()
        if expires < earliest:
            raise ValueError(
                f"connection '{label}' expiry must be on or after {earliest.isoformat()}"
            )
    return expires.isoformat()


def parse_enabled(raw: object, *, default: bool = True) -> bool:
    """Normalize an optional enabled flag; missing key → ``default`` (backward compatible)."""
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("", "default"):
        return default
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def parse_connections(raw: list | None, *, enforce_expiry_future: bool = True) -> list[dict]:
    """Validate and normalize connection dicts from Settings / app_settings."""
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("connections must be a list")
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each connection must be an object")
        cid = str(item.get("id") or "").strip() or new_id()
        if cid in seen:
            raise ValueError(f"duplicate connection id: {cid}")
        seen.add(cid)
        label = str(item.get("label") or "").strip()
        if not label:
            raise ValueError("connection label is required")
        ctype = str(item.get("type") or "path").strip().lower()
        if ctype not in CONNECTION_TYPES:
            raise ValueError(f"unsupported connection type: {ctype}")
        base_uri = str(item.get("base_uri") or "").strip()
        if not base_uri:
            raise ValueError(f"connection '{label}' needs a base URI / path")
        kinds_raw = item.get("kinds") or []
        if isinstance(kinds_raw, str):
            kinds_raw = [k.strip() for k in kinds_raw.split(",") if k.strip()]
        kinds = sorted({str(k).strip().lower() for k in kinds_raw if str(k).strip()})
        bad = set(kinds) - CONNECTION_KINDS
        if bad:
            raise ValueError(f"unknown artifact types: {', '.join(sorted(bad))}")
        if not kinds:
            raise ValueError(f"connection '{label}' must select at least one artifact type")
        token = str(item.get("token") or "")
        expires_at = parse_expires_at(
            item.get("expires_at"),
            label=label,
            enforce_future=enforce_expiry_future,
        )
        provider = str(item.get("provider") or "").strip().lower()
        if ctype == "api":
            from lib import library_api as library_api_lib

            library_api_lib.register_builtins()
            if not provider:
                raise ValueError(f"connection '{label}' (api) needs a provider")
            if library_api_lib.get_adapter(provider) is None:
                known = ", ".join(p.id for p in library_api_lib.all_providers()) or "(none)"
                raise ValueError(
                    f"connection '{label}' has unknown API provider '{provider}' (known: {known})"
                )
        elif ctype == "forge":
            from lib import library_forge as library_forge_lib

            library_forge_lib.register_builtins()
            if not provider:
                raise ValueError(f"connection '{label}' (forge) needs a provider")
            if library_forge_lib.get_adapter(provider) is None:
                known = ", ".join(p.id for p in library_forge_lib.all_providers()) or "(none)"
                raise ValueError(
                    f"connection '{label}' has unknown forge provider '{provider}' (known: {known})"
                )
        else:
            provider = ""
        out.append(
            {
                "id": cid,
                "label": label,
                "type": ctype,
                "base_uri": base_uri,
                "token": token,
                "expires_at": expires_at,
                "kinds": kinds,
                "provider": provider,
                "enabled": parse_enabled(item.get("enabled"), default=True),
            }
        )
    return out


def connections_for_bindings(
    raw_connections: list | None,
    raw_bindings: list | None,
) -> list[dict]:
    """Parse only connections referenced by the given bindings (ignore unrelated rows)."""
    by_id: dict[str, dict] = {}
    for item in raw_connections or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if cid:
            by_id[cid] = item
    needed: list[dict] = []
    seen: set[str] = set()
    for binding in raw_bindings or []:
        if not isinstance(binding, dict):
            continue
        cid = str(binding.get("connection_id") or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        if cid in by_id:
            needed.append(by_id[cid])
    # Catalog/pull paths should not fail because a stored expiry is now in the past.
    return parse_connections(needed, enforce_expiry_future=False)


def parse_script_bindings(raw: list | None, connections: list[dict]) -> list[dict]:
    """Validate Scripts domain bindings against the connection registry."""
    return _parse_domain_bindings(
        raw,
        connections,
        domain="scripts",
        kind="scripts",
        noun="script",
    )


def parse_clutch_bindings(raw: list | None, connections: list[dict]) -> list[dict]:
    """Validate Clutches domain bindings against the connection registry."""
    return _parse_domain_bindings(
        raw,
        connections,
        domain="clutches",
        kind="clutches",
        noun="clutch",
    )


def parse_media_bindings(raw: list | None, connections: list[dict]) -> list[dict]:
    """Validate Media domain bindings (ISO / VirtIO cache target)."""
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("media bindings must be a list")
    by_id = {c["id"]: c for c in connections}
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each binding must be an object")
        bid = str(item.get("id") or "").strip() or new_id()
        if bid in seen:
            raise ValueError(f"duplicate binding id: {bid}")
        seen.add(bid)
        conn_id = str(item.get("connection_id") or "").strip()
        if not conn_id or conn_id not in by_id:
            raise ValueError("media binding references an unknown connection")
        conn = by_id[conn_id]
        if "media" not in conn["kinds"]:
            raise ValueError(
                f"connection '{conn['label']}' does not serve media - "
                "enable the media artifact type on the connection"
            )
        target = str(item.get("target") or "iso").strip().lower()
        if target not in MEDIA_TARGETS:
            raise ValueError(
                f"media binding target must be one of: {', '.join(sorted(MEDIA_TARGETS))}"
            )
        filt = str(item.get("filter") or "").strip() or "*"
        out.append(
            {
                "id": bid,
                "connection_id": conn_id,
                "label": _binding_label(item, filt),
                "filter": filt,
                "domain": "media",
                "target": target,
                "enabled": parse_enabled(item.get("enabled"), default=True),
            }
        )
    return out


def _binding_label(item: dict, filt: str) -> str:
    """Operator display name; defaults to filter when unset (#359)."""
    return str(item.get("label") or "").strip() or filt


def _parse_domain_bindings(
    raw: list | None,
    connections: list[dict],
    *,
    domain: str,
    kind: str,
    noun: str,
) -> list[dict]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{noun} bindings must be a list")
    by_id = {c["id"]: c for c in connections}
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each binding must be an object")
        bid = str(item.get("id") or "").strip() or new_id()
        if bid in seen:
            raise ValueError(f"duplicate binding id: {bid}")
        seen.add(bid)
        conn_id = str(item.get("connection_id") or "").strip()
        if not conn_id or conn_id not in by_id:
            raise ValueError(f"{noun} binding references an unknown connection")
        conn = by_id[conn_id]
        if kind not in conn["kinds"]:
            raise ValueError(
                f"connection '{conn['label']}' does not serve {kind} - "
                f"enable the {kind} artifact type on the connection"
            )
        filt = str(item.get("filter") or "").strip() or "*"
        out.append(
            {
                "id": bid,
                "connection_id": conn_id,
                "label": _binding_label(item, filt),
                "filter": filt,
                "domain": domain,
                "enabled": parse_enabled(item.get("enabled"), default=True),
            }
        )
    return out


def connection_is_enabled(conn: dict | None) -> bool:
    """True when the connection is enabled (missing flag → True)."""
    if not conn:
        return False
    return parse_enabled(conn.get("enabled"), default=True)


def binding_is_enabled(binding: dict | None) -> bool:
    """True when the binding's own enabled flag is on (missing → True)."""
    if not binding:
        return False
    return parse_enabled(binding.get("enabled"), default=True)


def binding_is_effective(binding: dict, connections_by_id: dict[str, dict]) -> bool:
    """Effective for Import/list/pull: ``connection.enabled AND binding.enabled``."""
    if not binding_is_enabled(binding):
        return False
    conn = connections_by_id.get(str(binding.get("connection_id") or ""))
    return connection_is_enabled(conn)


def enabled_connections(connections: list[dict]) -> list[dict]:
    """Return only connections with ``enabled`` true (default true)."""
    return [c for c in connections if connection_is_enabled(c)]


def effective_bindings(
    bindings: list[dict],
    connections: list[dict],
) -> list[dict]:
    """Return bindings that are effective given their parent connections."""
    by_id = {c["id"]: c for c in connections}
    return [b for b in bindings if binding_is_effective(b, by_id)]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_path_for(
    domain: str,
    cache_name: str,
    *,
    media_target: str | None = None,
    data_dir: Path | None = None,
) -> Path:
    """Return the operator-cache path for a domain basename."""
    from lib import config as config_lib

    root = data_dir or config_lib.data_dir()
    name = Path(cache_name).name
    domain_n = (domain or "").strip().lower()
    if domain_n == "scripts":
        return root / _SCRIPT_PULL_DEST / name
    if domain_n == "clutches":
        return root / _CLUTCH_PULL_DEST / name
    if domain_n == "media":
        target = (media_target or "iso").strip().lower()
        if target not in MEDIA_TARGETS:
            raise ValueError(f"media target must be one of: {', '.join(sorted(MEDIA_TARGETS))}")
        return root / "media" / target / name
    raise ValueError(f"unknown cache domain: {domain}")


def size_mtime_digest(path: Path) -> str:
    """Canonical path tip digest: ``{size}:{mtime_ns}``."""
    st = path.stat()
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))
    return f"{st.st_size}:{mtime_ns}"


def git_blob_sha_bytes(data: bytes) -> str:
    """Git blob object id for ``data`` (sha1 of ``blob {len}\\0{data}``)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def git_blob_sha_file(path: Path) -> str:
    """Git blob object id for file bytes at ``path``."""
    return git_blob_sha_bytes(path.read_bytes())


def content_identity_for_kind(path: Path, kind: str) -> str | None:
    """Return the content-addressable identity of ``path`` for tip kinds that allow it."""
    kind_n = (kind or "").strip().lower()
    if kind_n == "sha256":
        return sha256_file(path)
    if kind_n == "git_blob":
        return git_blob_sha_file(path)
    return None


def assert_pulled_matches_tip(
    dest: Path,
    tip: tuple[str, str] | None,
    *,
    content_sha256: str,
) -> None:
    """Raise if a content-addressable Library tip does not match the pulled file.

    Prevents marking provenance ``in_sync`` when a download returned stale bytes
    (e.g. CDN) while the tip API already advanced.
    """
    if tip is None:
        return
    kind, digest = tip
    kind_n = (kind or "").strip().lower()
    expected = (digest or "").strip().lower()
    if not expected:
        return
    if kind_n == "sha256":
        actual = (content_sha256 or "").strip().lower()
        if actual != expected:
            raise ValueError(
                "Pulled file does not match Library tip digest "
                f"(got {actual[:12]}…, tip {expected[:12]}…)"
            )
        return
    if kind_n == "git_blob":
        actual = git_blob_sha_file(dest)
        if actual != expected:
            raise ValueError(
                "Pulled file does not match Library git blob tip "
                f"(got {actual[:12]}…, tip {expected[:12]}…)"
            )


def _record_provenance(
    conn: dict,
    *,
    domain: str,
    relative_path: str,
    result: dict,
    binding_id: str | None = None,
    media_target: str | None = None,
) -> None:
    """Write provenance after a successful first pull (anchors = observed = in_sync)."""
    from lib import library_provenance as prov

    tip = resolve_source_digest(conn, relative_path)
    kind, digest = (tip[0], tip[1]) if tip else (None, None)
    dest = Path(str(result.get("dest") or ""))
    content_sha = str(result.get("sha256") or "")
    if tip is not None and dest.is_file():
        assert_pulled_matches_tip(dest, tip, content_sha256=content_sha)
    try:
        prov.upsert_on_pull(
            domain=domain,
            cache_name=result["name"],
            connection_id=str(conn.get("id") or ""),
            relative_path=relative_path.replace("\\", "/").lstrip("/"),
            source_type=str(conn.get("type") or ""),
            cache_sha256=content_sha,
            source_digest=digest,
            source_digest_kind=kind,
            binding_id=binding_id,
            media_target=media_target,
            drift_state="in_sync",
        )
    except Exception:
        # Provenance must not fail a successful first pull into cache.
        pass


class LibraryRateLimitError(Exception):
    """Remote tip API refused the request (e.g. GitHub 403/429)."""


@dataclass(frozen=True)
class TipResolveResult:
    """Outcome of a cheap tip resolve (ADR-0018 source_status inputs)."""

    status: str  # ok | missing | unconfirmable | unreachable
    tip: tuple[str, str] | None = None
    detail: str = ""


def tip_index_for_connection(conn: dict) -> dict[str, tuple[str, str]]:
    """Return ``{relative_path: (kind, digest)}`` for a connection (batched when possible).

    Raises ``LibraryRateLimitError`` when the provider signals rate limiting.
    """
    ctype = conn.get("type")
    if ctype == "forge":
        adapter = _forge_adapter(conn)
        getter = getattr(adapter, "tip_index", None)
        if callable(getter):
            return getter(conn)
    if ctype == "api":
        adapter = _api_adapter(conn)
        getter = getattr(adapter, "tip_index", None)
        if callable(getter):
            return getter(conn)
    return {}


def resolve_source_digest(
    conn: dict,
    relative_path: str,
    *,
    tip_index: dict[str, tuple[str, str]] | None = None,
    single_file: bool = False,
    tip_index_complete: bool = False,
) -> tuple[str, str] | None:
    """Return ``(kind, digest)`` for drift compare — never downloads a file body.

    Prefer :func:`resolve_source_tip` when callers need ADR-0018 status codes.
    ``tip_index_complete`` means a successful batch index is authoritative (path
    absent → missing, not a further resolve).
    """
    result = resolve_source_tip(
        conn,
        relative_path,
        tip_index=tip_index,
        single_file=single_file,
        tip_index_complete=tip_index_complete,
    )
    return result.tip if result.status == "ok" else None


def resolve_source_tip(
    conn: dict,
    relative_path: str,
    *,
    tip_index: dict[str, tuple[str, str]] | None = None,
    single_file: bool = False,
    tip_index_complete: bool = False,
) -> TipResolveResult:
    """Resolve tip identity with an explicit reachability outcome (ADR-0018)."""
    rel = relative_path.replace("\\", "/").lstrip("/")
    if not rel or ".." in Path(rel).parts:
        raise ValueError("Invalid relative path")
    if tip_index is not None and rel in tip_index:
        return TipResolveResult(status="ok", tip=tip_index[rel])
    if tip_index_complete and tip_index is not None:
        return TipResolveResult(
            status="missing",
            detail="Path not present in source tip index",
        )
    ctype = conn.get("type")
    if ctype == "path":
        src = _expand_base(conn["base_uri"]) / rel
        if not src.is_file():
            return TipResolveResult(status="missing")
        return TipResolveResult(status="ok", tip=("size_mtime", size_mtime_digest(src)))
    if ctype == "https":
        return _https_source_tip(conn, rel)
    if ctype == "git":
        return TipResolveResult(status="unreachable", detail=_LEGACY_GIT_REMOVED_MSG)
    if ctype == "api":
        return _adapter_source_tip(conn, rel, single_file=single_file, forge=False)
    if ctype == "forge":
        return _adapter_source_tip(conn, rel, single_file=single_file, forge=True)
    return TipResolveResult(
        status="unconfirmable",
        detail=f"Unsupported connection type: {ctype}",
    )


def _adapter_source_tip(
    conn: dict,
    rel: str,
    *,
    single_file: bool,
    forge: bool,
) -> TipResolveResult:
    adapter = _forge_adapter(conn) if forge else _api_adapter(conn)
    try:
        if single_file:
            one = getattr(adapter, "source_digest_one", None)
            if callable(one):
                tip = one(conn, rel)
                if tip:
                    return TipResolveResult(status="ok", tip=tip)
                return TipResolveResult(status="missing")
        getter = getattr(adapter, "source_digest", None)
        if callable(getter):
            tip = getter(conn, rel)
            if tip:
                return TipResolveResult(status="ok", tip=tip)
            return TipResolveResult(status="missing")
    except LibraryRateLimitError:
        raise
    except Exception as exc:
        return TipResolveResult(status="unreachable", detail=str(exc)[:240])
    return TipResolveResult(
        status="unconfirmable",
        detail="Provider cannot confirm tip without a body download",
    )


def _https_source_digest(conn: dict, rel: str) -> tuple[str, str] | None:
    result = _https_source_tip(conn, rel)
    return result.tip if result.status == "ok" else None


def _https_source_tip(conn: dict, rel: str) -> TipResolveResult:
    url = conn["base_uri"].rstrip("/") + "/" + rel
    req = Request(url, method="HEAD")
    token = (conn.get("token") or "").strip()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(req, timeout=30) as resp:
            headers = getattr(resp, "headers", None) or {}
            sha = (
                headers.get("X-Checksum-Sha256")
                or headers.get("x-checksum-sha256")
                or headers.get("Digest")
                or ""
            )
            sha = str(sha).strip().lower()
            if sha.startswith("sha-256="):
                sha = sha.split("=", 1)[1].strip()
            if re.fullmatch(r"[0-9a-f]{64}", sha):
                return TipResolveResult(status="ok", tip=("sha256", sha))
            return TipResolveResult(status="unconfirmable")
    except HTTPError as exc:
        if int(getattr(exc, "code", 0) or 0) == 404:
            return TipResolveResult(status="missing", detail="HTTP 404")
        return TipResolveResult(
            status="unreachable",
            detail=f"HTTP {getattr(exc, 'code', '?')}",
        )
    except (URLError, OSError) as exc:
        return TipResolveResult(status="unreachable", detail=str(exc)[:240])


def _expand_base(base_uri: str) -> Path:
    return Path(base_uri).expanduser().resolve()


def test_connection(conn: dict) -> dict:
    """Return {ok, message} for a connection reachability check."""
    ctype = conn["type"]
    if ctype == "path":
        root = Path(conn["base_uri"]).expanduser()
        if not root.exists():
            return {"ok": False, "message": f"Path does not exist: {root}"}
        if not root.is_dir():
            return {"ok": False, "message": f"Path is not a directory: {root}"}
        if not os_access_dir(root):
            return {"ok": False, "message": f"Path is not readable: {root}"}
        return {"ok": True, "message": f"Reachable directory: {root.resolve()}"}
    if ctype == "https":
        return _test_https(conn)
    if ctype == "git":
        return {"ok": False, "message": _LEGACY_GIT_REMOVED_MSG}
    if ctype == "api":
        return _test_api(conn)
    if ctype == "forge":
        return _test_forge(conn)
    return {"ok": False, "message": f"Unsupported type: {ctype}"}


def os_access_dir(path: Path) -> bool:
    try:
        next(path.iterdir(), None)
        return True
    except OSError:
        return False


def _legacy_git_cache_path_for_id(connection_id: str) -> Path:
    """Return leftover ``{data_dir}/library/git/{connection_id}`` if any (ADR-0020 GC)."""
    from lib import config as config_lib

    cid = str(connection_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", cid):
        raise ValueError(f"invalid connection id for legacy git cache: {cid!r}")
    return config_lib.data_dir() / _LEGACY_GIT_CACHE_SUBDIR / cid


def _rmtree_portable(path: Path) -> None:
    """Recursively remove ``path`` on Linux / macOS / Windows Controllers.

    Clears read-only bits on failure (common under ``.git`` on Windows) then retries.
    """
    import stat

    def _onexc(func, p, exc_info=None):  # noqa: ARG001 - shutil signature varies
        target = Path(p)
        try:
            if target.exists():
                target.chmod(stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
                func(p)
        except OSError:
            raise

    # Python 3.12+ prefers onexc; 3.11 still uses onerror.
    try:
        shutil.rmtree(path, onexc=_onexc)
    except TypeError:
        shutil.rmtree(path, onerror=lambda func, p, _err: _onexc(func, p))


def purge_legacy_git_cache(connection_id: str) -> bool:
    """Remove a leftover classic git clone dir for ``connection_id`` if present.

    Returns True when a directory was removed. No-op (False) when missing.
    Refuses paths that resolve outside ``{data_dir}/library/git/``.
    """
    from lib import config as config_lib

    cache = _legacy_git_cache_path_for_id(connection_id)
    root = (config_lib.data_dir() / _LEGACY_GIT_CACHE_SUBDIR).resolve()
    try:
        resolved = cache.resolve(strict=False)
    except OSError as exc:
        raise ValueError(f"cannot resolve legacy git cache path: {exc}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("legacy git cache path escapes library/git root") from exc
    if not cache.exists():
        return False
    if not cache.is_dir():
        raise ValueError(f"legacy git cache path is not a directory: {cache}")
    _rmtree_portable(cache)
    return True


def _api_adapter(conn: dict):
    from lib import library_api as library_api_lib

    library_api_lib.register_builtins()
    provider = str(conn.get("provider") or "").strip().lower()
    adapter = library_api_lib.get_adapter(provider)
    if adapter is None:
        raise ValueError(f"Unknown or missing API provider: {provider or '(empty)'}")
    return adapter


def _test_api(conn: dict) -> dict:
    try:
        return _api_adapter(conn).test(conn)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}


def _list_api_files(
    conn: dict,
    filt: str,
    *,
    extensions: frozenset[str],
    limit: int | None,
) -> list[dict]:
    return _api_adapter(conn).list_hits(conn, filt, extensions=extensions, limit=limit)


def _forge_adapter(conn: dict):
    from lib import library_forge as library_forge_lib

    library_forge_lib.register_builtins()
    provider = str(conn.get("provider") or "").strip().lower()
    adapter = library_forge_lib.get_adapter(provider)
    if adapter is None:
        raise ValueError(f"Unknown or missing forge provider: {provider or '(empty)'}")
    return adapter


def _test_forge(conn: dict) -> dict:
    try:
        return _forge_adapter(conn).test(conn)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}


def _list_forge_files(
    conn: dict,
    filt: str,
    *,
    extensions: frozenset[str],
    limit: int | None,
) -> list[dict]:
    return _forge_adapter(conn).list_hits(conn, filt, extensions=extensions, limit=limit)


def _test_https(conn: dict) -> dict:
    url = conn["base_uri"].rstrip("/") + "/"
    req = Request(url, method="HEAD")
    token = (conn.get("token") or "").strip()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(req, timeout=10) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return {"ok": True, "message": f"HTTP {code} from {url}"}
    except HTTPError as exc:
        # Some servers reject HEAD — try GET lightly.
        if exc.code in (403, 405):
            try:
                greq = Request(url, method="GET")
                if token:
                    greq.add_header("Authorization", f"Bearer {token}")
                with urlopen(greq, timeout=10) as resp:
                    code = getattr(resp, "status", None) or resp.getcode()
                    return {"ok": True, "message": f"HTTP {code} from {url}"}
            except Exception as exc2:
                return {"ok": False, "message": str(exc2)}
        return {"ok": False, "message": f"HTTP {exc.code}: {exc.reason}"}
    except URLError as exc:
        return {"ok": False, "message": str(exc.reason if hasattr(exc, "reason") else exc)}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def list_script_hits(
    conn: dict,
    filt: str,
    *,
    limit: int | None = None,
) -> list[dict]:
    """List script files for a connection + filter."""
    return list_hits(conn, filt, extensions=SCRIPT_EXTENSIONS, limit=limit)


def list_clutch_hits(
    conn: dict,
    filt: str,
    *,
    limit: int | None = None,
) -> list[dict]:
    """List Clutch (.yaml) files for a connection + filter."""
    return list_hits(conn, filt, extensions=CLUTCH_EXTENSIONS, limit=limit)


def list_media_hits(
    conn: dict,
    filt: str,
    *,
    limit: int | None = None,
) -> list[dict]:
    """List media (.iso) files for a connection + filter."""
    return list_hits(conn, filt, extensions=MEDIA_EXTENSIONS, limit=limit)


def list_hits(
    conn: dict,
    filt: str,
    *,
    extensions: frozenset[str],
    limit: int | None = None,
) -> list[dict]:
    """List files for a connection + filter limited to ``extensions``."""
    ctype = conn["type"]
    if ctype == "path":
        return _list_path_files(conn, filt, extensions=extensions, limit=limit)
    if ctype == "https":
        return _list_https_files(conn, filt, extensions=extensions, limit=limit)
    if ctype == "git":
        raise ValueError(_LEGACY_GIT_REMOVED_MSG)
    if ctype == "api":
        return _list_api_files(conn, filt, extensions=extensions, limit=limit)
    if ctype == "forge":
        return _list_forge_files(conn, filt, extensions=extensions, limit=limit)
    raise ValueError(f"Unsupported connection type: {ctype}")


def _normalize_filter(filt: str) -> str:
    f = (filt or "*").strip().replace("\\", "/")
    while f.startswith("./"):
        f = f[2:]
    return f or "*"


def _list_path_files(
    conn: dict,
    filt: str,
    *,
    extensions: frozenset[str],
    limit: int | None,
) -> list[dict]:
    root = _expand_base(conn["base_uri"])
    if not root.is_dir():
        raise ValueError(f"Connection path is not a directory: {root}")
    return _list_tree_files(
        root,
        filt,
        extensions=extensions,
        limit=limit,
        connection_id=conn["id"],
        source_type="path",
    )


def _list_tree_files(
    root: Path,
    filt: str,
    *,
    extensions: frozenset[str],
    limit: int | None,
    connection_id: str,
    source_type: str,
) -> list[dict]:
    pattern = _normalize_filter(filt)
    hits: list[dict] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        # Skip git metadata inside checkouts
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if ".git" in rel_parts:
            continue
        if path.suffix.lower() not in extensions:
            continue
        rel = path.relative_to(root).as_posix()
        if not _match_filter(rel, pattern):
            continue
        hits.append(
            {
                "name": path.name,
                "relative_path": rel,
                "sha256": sha256_file(path),
                "connection_id": connection_id,
                "source_type": source_type,
            }
        )
        if limit is not None and len(hits) >= limit:
            break
    return hits


def _match_filter(relative_path: str, pattern: str) -> bool:
    if pattern in ("*", "**", "**/*"):
        return True
    if fnmatch(relative_path, pattern):
        return True
    if "/" not in pattern and fnmatch(Path(relative_path).name, pattern):
        return True
    return False


def path_matches_filter(relative_path: str, pattern: str) -> bool:
    """Public binding/catalog path glob match (fnmatch; basename-only patterns OK)."""
    return _match_filter(relative_path, pattern)


def _list_https_files(
    conn: dict,
    filt: str,
    *,
    extensions: frozenset[str],
    limit: int | None,
) -> list[dict]:
    """HTTPS: filter must be one or more relative file paths (newline or comma separated)."""
    pattern = _normalize_filter(filt)
    parts = [p.strip() for p in re.split(r"[\n,]+", pattern) if p.strip()]
    if not parts or parts == ["*"]:
        raise ValueError(
            "HTTPS connections need an explicit relative file path in the filter "
            "(directory listing is not supported)"
        )
    hits: list[dict] = []
    for rel in parts:
        rel = rel.lstrip("/")
        name = Path(rel).name
        if Path(name).suffix.lower() not in extensions:
            continue
        url = conn["base_uri"].rstrip("/") + "/" + rel
        req = Request(url, method="HEAD")
        token = (conn.get("token") or "").strip()
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urlopen(req, timeout=15) as resp:
                _ = resp.status if hasattr(resp, "status") else resp.getcode()
        except Exception as exc:
            raise ValueError(f"Cannot reach {url}: {exc}") from exc
        hits.append(
            {
                "name": name,
                "relative_path": rel,
                "sha256": None,
                "connection_id": conn["id"],
                "source_type": "https",
            }
        )
        if limit is not None and len(hits) >= limit:
            break
    return hits


def test_filter(conn: dict, filt: str, *, domain: str = "scripts") -> dict:
    """Return {ok, message, hits} with up to _SAMPLE_LIMIT matches."""
    domain = (domain or "scripts").strip().lower()
    list_by_domain = {
        "scripts": (list_script_hits, "script"),
        "media": (list_media_hits, "media"),
        "clutches": (list_clutch_hits, "clutch"),
    }
    list_fn, noun = list_by_domain.get(domain, (list_script_hits, "script"))
    try:
        hits = list_fn(conn, filt, limit=_SAMPLE_LIMIT)
    except ValueError as exc:
        return {"ok": False, "message": str(exc), "hits": []}
    if not hits:
        return {
            "ok": True,
            "message": (
                f"Connected, but no {noun} files matched this filter "
                f"(sample limit {_SAMPLE_LIMIT})."
            ),
            "hits": [],
        }
    names = ", ".join(h["name"] for h in hits)
    more = "" if len(hits) < _SAMPLE_LIMIT else " (sample capped)"
    return {
        "ok": True,
        "message": f"Found {len(hits)} sample hit(s){more}: {names}",
        "hits": hits,
    }


def pull_script(
    conn: dict,
    relative_path: str,
    *,
    dest_dir: Path | None = None,
    binding_id: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Copy one script into the operator automation/scripts cache."""
    from lib import config as config_lib

    dest_root = dest_dir or (config_lib.data_dir() / _SCRIPT_PULL_DEST)
    result = _pull_file(
        conn,
        relative_path,
        dest_root=dest_root,
        extensions=SCRIPT_EXTENSIONS,
        kind_label="script",
        overwrite=overwrite,
    )
    if overwrite:
        tip = resolve_source_digest(conn, relative_path, single_file=True)
        dest = Path(str(result.get("dest") or ""))
        if dest.is_file():
            assert_pulled_matches_tip(dest, tip, content_sha256=str(result.get("sha256") or ""))
    else:
        _record_provenance(
            conn,
            domain="scripts",
            relative_path=relative_path,
            result=result,
            binding_id=binding_id,
        )
    return result


def sync_script(
    conn: dict,
    relative_path: str,
    *,
    dest_dir: Path | None = None,
    binding_id: str | None = None,
) -> dict:
    """Overwrite a cached script from its Library source (no provenance upsert)."""
    return pull_script(
        conn,
        relative_path,
        dest_dir=dest_dir,
        binding_id=binding_id,
        overwrite=True,
    )


def pull_clutch(
    conn: dict,
    relative_path: str,
    *,
    dest_dir: Path | None = None,
    binding_id: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Copy one Clutch into the operator clutches/ cache."""
    from lib import config as config_lib

    dest_root = dest_dir or (config_lib.data_dir() / _CLUTCH_PULL_DEST)
    result = _pull_file(
        conn,
        relative_path,
        dest_root=dest_root,
        extensions=CLUTCH_EXTENSIONS,
        kind_label="clutch",
        overwrite=overwrite,
    )
    if overwrite:
        tip = resolve_source_digest(conn, relative_path, single_file=True)
        dest = Path(str(result.get("dest") or ""))
        if dest.is_file():
            assert_pulled_matches_tip(dest, tip, content_sha256=str(result.get("sha256") or ""))
    else:
        _record_provenance(
            conn,
            domain="clutches",
            relative_path=relative_path,
            result=result,
            binding_id=binding_id,
        )
    return result


def sync_clutch(
    conn: dict,
    relative_path: str,
    *,
    dest_dir: Path | None = None,
    binding_id: str | None = None,
) -> dict:
    """Overwrite a cached Clutch from its Library source (no provenance upsert)."""
    return pull_clutch(
        conn,
        relative_path,
        dest_dir=dest_dir,
        binding_id=binding_id,
        overwrite=True,
    )


def pull_media(
    conn: dict,
    relative_path: str,
    *,
    target: str,
    dest_dir: Path | None = None,
    binding_id: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Copy one media file into media/iso or media/virtio."""
    from lib import config as config_lib

    target_norm = (target or "").strip().lower()
    if target_norm not in MEDIA_TARGETS:
        raise ValueError(f"media target must be one of: {', '.join(sorted(MEDIA_TARGETS))}")
    dest_root = dest_dir or (config_lib.data_dir() / "media" / target_norm)
    result = _pull_file(
        conn,
        relative_path,
        dest_root=dest_root,
        extensions=MEDIA_EXTENSIONS,
        kind_label="media",
        overwrite=overwrite,
    )
    if overwrite:
        tip = resolve_source_digest(conn, relative_path, single_file=True)
        dest = Path(str(result.get("dest") or ""))
        if dest.is_file():
            assert_pulled_matches_tip(dest, tip, content_sha256=str(result.get("sha256") or ""))
    else:
        _record_provenance(
            conn,
            domain="media",
            relative_path=relative_path,
            result=result,
            binding_id=binding_id,
            media_target=target_norm,
        )
    return result


def sync_media(
    conn: dict,
    relative_path: str,
    *,
    target: str,
    dest_dir: Path | None = None,
    binding_id: str | None = None,
) -> dict:
    """Overwrite a cached media file from its Library source."""
    return pull_media(
        conn,
        relative_path,
        target=target,
        dest_dir=dest_dir,
        binding_id=binding_id,
        overwrite=True,
    )


def _pull_file(
    conn: dict,
    relative_path: str,
    *,
    dest_root: Path,
    extensions: frozenset[str],
    kind_label: str,
    overwrite: bool = False,
) -> dict:
    rel = relative_path.replace("\\", "/").lstrip("/")
    if ".." in Path(rel).parts:
        raise ValueError("Invalid relative path")
    name = Path(rel).name
    if Path(name).suffix.lower() not in extensions:
        raise ValueError(f"Unsupported {kind_label} type: {name}")

    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / name
    if dest.exists() and not overwrite:
        raise FileExistsError(f"Already in cache: {name}")

    ctype = conn["type"]
    if ctype == "path":
        src = _expand_base(conn["base_uri"]) / rel
        if not src.is_file():
            raise FileNotFoundError(f"Not found on connection: {rel}")
        shutil.copy2(src, dest)
        digest = sha256_file(dest)
        return {"name": name, "sha256": digest, "dest": str(dest)}
    if ctype == "https":
        url = conn["base_uri"].rstrip("/") + "/" + rel
        req = Request(url, method="GET")
        token = (conn.get("token") or "").strip()
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
                shutil.copyfileobj(resp, out)
        except Exception:
            if not overwrite:
                dest.unlink(missing_ok=True)
            raise
        digest = sha256_file(dest)
        return {"name": name, "sha256": digest, "dest": str(dest)}
    if ctype == "git":
        raise ValueError(_LEGACY_GIT_REMOVED_MSG)
    if ctype == "api":
        adapter = _api_adapter(conn)
        return adapter.pull_file(conn, rel, dest)
    if ctype == "forge":
        adapter = _forge_adapter(conn)
        return adapter.pull_file(conn, rel, dest)
    raise ValueError(f"Pull not supported for type: {ctype}")


def catalog_scripts(connections: list[dict], bindings: list[dict]) -> list[dict]:
    """Union of script hits across Scripts bindings (dedupe by name, first wins)."""
    return _catalog(connections, bindings, list_fn=list_script_hits)


def catalog_clutches(connections: list[dict], bindings: list[dict]) -> list[dict]:
    """Union of Clutch hits across Clutches bindings (dedupe by name, first wins)."""
    return _catalog(connections, bindings, list_fn=list_clutch_hits)


def catalog_media(
    connections: list[dict],
    bindings: list[dict],
    *,
    target: str | None = None,
) -> list[dict]:
    """Union of media hits across Media bindings (optional target filter)."""
    target_norm = (target or "").strip().lower() or None
    if target_norm and target_norm not in MEDIA_TARGETS:
        raise ValueError(f"media target must be one of: {', '.join(sorted(MEDIA_TARGETS))}")
    filtered = bindings
    if target_norm:
        filtered = [b for b in bindings if b.get("target") == target_norm]
    items = _catalog(connections, filtered, list_fn=list_media_hits)
    for item in items:
        # Preserve binding target on catalog rows for UI context.
        bid = item.get("binding_id")
        for binding in filtered:
            if binding["id"] == bid:
                item["target"] = binding.get("target")
                break
    return items


def _catalog(
    connections: list[dict],
    bindings: list[dict],
    *,
    list_fn,
) -> list[dict]:
    by_id = {c["id"]: c for c in connections}
    seen_names: set[str] = set()
    out: list[dict] = []
    for binding in bindings:
        if not binding_is_effective(binding, by_id):
            continue
        conn = by_id.get(binding["connection_id"])
        if not conn:
            continue
        try:
            hits = list_fn(conn, binding.get("filter") or "*", limit=None)
        except ValueError:
            continue
        for hit in hits:
            if hit["name"] in seen_names:
                continue
            seen_names.add(hit["name"])
            out.append(
                {
                    **hit,
                    "binding_id": binding["id"],
                    "connection_label": conn["label"],
                }
            )
    out.sort(key=lambda h: h["name"].lower())
    return out


def annotate_cached(items: list[dict], cached_names: set[str] | list[str]) -> list[dict]:
    """Mark catalog hits whose basename is already in the operator cache."""
    names = {str(n) for n in cached_names}
    out: list[dict] = []
    for item in items:
        row = dict(item)
        row["cached"] = str(row.get("name") or "") in names
        out.append(row)
    return out


def catalog_content_union(
    *,
    connections: list[dict],
    script_bindings: list[dict],
    clutch_bindings: list[dict],
    media_bindings: list[dict],
    script_cached_names: set[str] | list[str],
    clutch_cached_names: set[str] | list[str],
    media_cached_names: set[str] | list[str],
    domain: str | None = None,
) -> list[dict]:
    """Cross-domain catalog for Library → Content Available (#392).

    Stamps each row with ``domain`` (and media ``target`` from bindings).
    Optional ``domain`` filters to scripts | clutches | media.
    """
    domain_norm = (domain or "").strip().lower() or None
    if domain_norm and domain_norm not in ("scripts", "clutches", "media"):
        raise ValueError("domain must be scripts, clutches, or media")

    out: list[dict] = []
    if domain_norm in (None, "scripts"):
        script_conns = connections_for_bindings(connections, script_bindings)
        scripts = annotate_cached(
            catalog_scripts(script_conns, parse_script_bindings(script_bindings, script_conns)),
            script_cached_names,
        )
        for item in scripts:
            row = dict(item)
            row["domain"] = "scripts"
            out.append(row)

    if domain_norm in (None, "clutches"):
        clutch_conns = connections_for_bindings(connections, clutch_bindings)
        clutches = annotate_cached(
            catalog_clutches(clutch_conns, parse_clutch_bindings(clutch_bindings, clutch_conns)),
            clutch_cached_names,
        )
        for item in clutches:
            row = dict(item)
            row["domain"] = "clutches"
            out.append(row)

    if domain_norm in (None, "media"):
        media_conns = connections_for_bindings(connections, media_bindings)
        media_items = annotate_cached(
            catalog_media(media_conns, parse_media_bindings(media_bindings, media_conns)),
            media_cached_names,
        )
        for item in media_items:
            row = dict(item)
            row["domain"] = "media"
            out.append(row)

    out.sort(
        key=lambda h: (
            str(h.get("domain") or ""),
            str(h.get("name") or "").lower(),
            str(h.get("relative_path") or "").lower(),
        )
    )
    return out
