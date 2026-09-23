"""Library connections and domain bindings — list, test, and pull into the operator cache.

``path`` (local or mounted share), ``https`` (single relative file), ``git``
(shallow clone cache), ``api`` (pluggable catalog providers — #255), and ``forge``
(pluggable git forge providers — #307) are supported.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import uuid
from datetime import date, timedelta
from fnmatch import fnmatch
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen

from lib.import_files import SCRIPT_EXTENSIONS

CONNECTION_TYPES = frozenset({"path", "https", "git", "api", "forge"})
CONNECTION_KINDS = frozenset({"scripts", "clutches", "media", "packages"})
MEDIA_EXTENSIONS = frozenset({".iso"})
MEDIA_TARGETS = frozenset({"iso", "virtio"})
CLUTCH_EXTENSIONS = frozenset({".yaml"})
_SAMPLE_LIMIT = 5
_SCRIPT_PULL_DEST = "automation/scripts"
_CLUTCH_PULL_DEST = "clutches"
_GIT_CACHE_SUBDIR = "library/git"
_GIT_TIMEOUT_S = 120


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
        label="script",
    )


def parse_clutch_bindings(raw: list | None, connections: list[dict]) -> list[dict]:
    """Validate Clutches domain bindings against the connection registry."""
    return _parse_domain_bindings(
        raw,
        connections,
        domain="clutches",
        kind="clutches",
        label="clutch",
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
                "filter": filt,
                "domain": "media",
                "target": target,
                "enabled": parse_enabled(item.get("enabled"), default=True),
            }
        )
    return out


def _parse_domain_bindings(
    raw: list | None,
    connections: list[dict],
    *,
    domain: str,
    kind: str,
    label: str,
) -> list[dict]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{label} bindings must be a list")
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
            raise ValueError(f"{label} binding references an unknown connection")
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
) -> tuple[str, str] | None:
    """Return ``(kind, digest)`` for drift compare — never downloads a file body.

    Returns None when tip identity cannot be obtained cheaply (→ drift ``unknown``).
    When ``tip_index`` is provided, prefer that map (pass-scoped forge Trees batch).
    ``single_file`` asks adapters for a cheap one-path tip (e.g. GitHub Contents).
    """
    rel = relative_path.replace("\\", "/").lstrip("/")
    if not rel or ".." in Path(rel).parts:
        raise ValueError("Invalid relative path")
    if tip_index is not None and rel in tip_index:
        return tip_index[rel]
    ctype = conn.get("type")
    if ctype == "path":
        src = _expand_base(conn["base_uri"]) / rel
        if not src.is_file():
            return None
        return ("size_mtime", size_mtime_digest(src))
    if ctype == "https":
        return _https_source_digest(conn, rel)
    if ctype == "git":
        return _git_blob_digest(conn, rel)
    if ctype == "api":
        adapter = _api_adapter(conn)
        if single_file:
            one = getattr(adapter, "source_digest_one", None)
            if callable(one):
                return one(conn, rel)
        getter = getattr(adapter, "source_digest", None)
        if callable(getter):
            return getter(conn, rel)
        return None
    if ctype == "forge":
        adapter = _forge_adapter(conn)
        if single_file:
            one = getattr(adapter, "source_digest_one", None)
            if callable(one):
                return one(conn, rel)
        getter = getattr(adapter, "source_digest", None)
        if callable(getter):
            return getter(conn, rel)
        return None
    return None


def _https_source_digest(conn: dict, rel: str) -> tuple[str, str] | None:
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
                return ("sha256", sha)
    except (HTTPError, URLError, OSError):
        return None
    return None


def _git_blob_digest(conn: dict, rel: str) -> tuple[str, str] | None:
    if not git_available():
        return None
    try:
        root = ensure_git_checkout(conn)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return None
    result = _run_git(["ls-tree", "HEAD", "--", rel], cwd=root, timeout=60)
    if result.returncode != 0:
        return None
    line = (result.stdout or "").strip().splitlines()
    if not line:
        return None
    # mode type sha\tpath
    parts = line[0].split()
    if len(parts) < 3:
        return None
    sha = parts[2]
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        return None
    return ("git_blob", sha)


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
        return _test_git(conn)
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


def git_available() -> bool:
    """True when the Controller has a ``git`` executable on PATH."""
    return shutil.which("git") is not None


def git_remote_url(base_uri: str, token: str = "") -> str:
    """Return a clone/ls-remote URL, embedding ``token`` for HTTPS remotes.

    SSH and ``file://`` / local-path remotes are returned unchanged (token ignored).
    GitHub hosts use ``x-access-token``; other HTTPS hosts use ``oauth2`` (GitLab-style).
    """
    uri = (base_uri or "").strip()
    if not uri:
        raise ValueError("git connection needs a repository URL")
    token = (token or "").strip()
    if not token:
        return uri
    # Local path / file URL / scp-style SSH — token does not apply
    if uri.startswith("git@") or uri.startswith("/") or uri.startswith("file:"):
        return uri
    if re.match(r"^[A-Za-z]:[\\/]", uri):
        return uri
    # scp-style user@host:path (no scheme)
    if "://" not in uri and re.match(r"^[^/]+@[^/]+:", uri):
        return uri
    parsed = urlparse(uri)
    if parsed.scheme not in ("http", "https"):
        return uri
    host = (parsed.hostname or "").lower()
    port = f":{parsed.port}" if parsed.port else ""
    user = (
        "x-access-token"
        if host in ("github.com", "www.github.com", "gist.github.com")
        else "oauth2"
    )
    netloc = f"{user}:{quote(token, safe='')}@{host}{port}"
    return urlunparse((parsed.scheme, netloc, parsed.path or "", "", "", ""))


def _git_env() -> dict[str, str]:
    """Env for non-interactive git (no credential prompts)."""
    import os

    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    return env


def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = _GIT_TIMEOUT_S,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=_git_env(),
    )


def _git_error_detail(result: subprocess.CompletedProcess[str]) -> str:
    err = (result.stderr or result.stdout or "").strip()
    # Never echo URLs that may embed tokens — keep the last non-URL line.
    lines = [ln for ln in err.splitlines() if "://" not in ln and "@" not in ln]
    detail = lines[-1] if lines else err.splitlines()[-1] if err else f"exit {result.returncode}"
    return detail[:300]


def _test_git(conn: dict) -> dict:
    if not git_available():
        return {
            "ok": False,
            "message": "git is not installed on this Hatchery Controller - install git to use Library git connections.",
        }
    try:
        url = git_remote_url(conn["base_uri"], conn.get("token") or "")
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    try:
        result = _run_git(["ls-remote", "--heads", url], timeout=60)
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "git ls-remote timed out"}
    except OSError as exc:
        return {"ok": False, "message": str(exc)}
    if result.returncode != 0:
        return {"ok": False, "message": f"git ls-remote failed: {_git_error_detail(result)}"}
    heads = [ln for ln in (result.stdout or "").splitlines() if ln.strip()]
    if not heads:
        return {"ok": False, "message": "Repository reachable but has no heads (empty?)"}
    display = (conn.get("base_uri") or "").strip()
    return {"ok": True, "message": f"Git remote OK ({len(heads)} head(s)): {display}"}


def git_cache_dir(conn: dict) -> Path:
    """Return the per-connection shallow clone path under the data directory."""
    return git_cache_path_for_id(str(conn.get("id") or "").strip() or "unknown")


def git_cache_path_for_id(connection_id: str) -> Path:
    """Return ``{data_dir}/library/git/{connection_id}`` for a connection id."""
    from lib import config as config_lib

    cid = str(connection_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", cid):
        raise ValueError(f"invalid connection id for git cache: {cid!r}")
    return config_lib.data_dir() / _GIT_CACHE_SUBDIR / cid


def _rmtree_portable(path: Path) -> None:
    """Recursively remove ``path`` on Linux / macOS / Windows Controllers.

    Clears read-only bits on failure (common under ``.git`` on Windows) then retries.
    """
    import stat

    def _onexc(func, p, exc_info=None):  # noqa: ARG001 — shutil signature varies
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


def delete_git_cache(connection_id: str) -> bool:
    """Remove the shallow clone cache for ``connection_id`` if present.

    Returns True when a directory was removed. No-op (False) when missing.
    Refuses paths that resolve outside ``{data_dir}/library/git/``.
    """
    from lib import config as config_lib

    cache = git_cache_path_for_id(connection_id)
    root = (config_lib.data_dir() / _GIT_CACHE_SUBDIR).resolve()
    try:
        resolved = cache.resolve(strict=False)
    except OSError as exc:
        raise ValueError(f"cannot resolve git cache path: {exc}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("git cache path escapes library/git root") from exc
    if not cache.exists():
        return False
    if not cache.is_dir():
        raise ValueError(f"git cache path is not a directory: {cache}")
    _rmtree_portable(cache)
    return True


def _configure_git_cache_line_endings(cache: Path) -> None:
    """Disable CRLF conversion so working-tree bytes match git blob tips (#308).

    Windows Controllers often default ``core.autocrlf=true``, which rewrites text
    files on checkout and breaks ``git_blob`` provenance / pull verification.
    """
    for key, value in (("core.autocrlf", "false"), ("core.eol", "lf")):
        cfg = _run_git(["config", key, value], cwd=cache, timeout=30)
        if cfg.returncode != 0:
            raise ValueError(f"git config {key} failed: {_git_error_detail(cfg)}")


def ensure_git_checkout(conn: dict) -> Path:
    """Clone or update a shallow checkout for ``conn``; return the working tree path."""
    if not git_available():
        raise ValueError(
            "git is not installed on this Hatchery Controller - install git to use Library git connections."
        )
    url = git_remote_url(conn["base_uri"], conn.get("token") or "")
    cache = git_cache_dir(conn)
    cache.parent.mkdir(parents=True, exist_ok=True)
    git_dir = cache / ".git"
    try:
        if not git_dir.is_dir():
            if cache.exists():
                _rmtree_portable(cache)
            # -c flags apply during the initial checkout before repo config exists.
            result = _run_git(
                [
                    "-c",
                    "core.autocrlf=false",
                    "-c",
                    "core.eol=lf",
                    "clone",
                    "--depth",
                    "1",
                    "--single-branch",
                    url,
                    str(cache),
                ],
                timeout=_GIT_TIMEOUT_S,
            )
            if result.returncode != 0:
                if cache.exists():
                    try:
                        _rmtree_portable(cache)
                    except OSError:
                        shutil.rmtree(cache, ignore_errors=True)
                raise ValueError(f"git clone failed: {_git_error_detail(result)}")
            _configure_git_cache_line_endings(cache)
        else:
            _configure_git_cache_line_endings(cache)
            fetch = _run_git(
                ["fetch", "--depth", "1", "origin"],
                cwd=cache,
                timeout=_GIT_TIMEOUT_S,
            )
            if fetch.returncode != 0:
                raise ValueError(f"git fetch failed: {_git_error_detail(fetch)}")
            reset = _run_git(
                ["reset", "--hard", "FETCH_HEAD"],
                cwd=cache,
                timeout=60,
            )
            if reset.returncode != 0:
                raise ValueError(f"git reset failed: {_git_error_detail(reset)}")
    except subprocess.TimeoutExpired as exc:
        raise ValueError("git operation timed out") from exc
    return cache


def _list_git_files(
    conn: dict,
    filt: str,
    *,
    extensions: frozenset[str],
    limit: int | None,
) -> list[dict]:
    root = ensure_git_checkout(conn)
    return _list_tree_files(
        root,
        filt,
        extensions=extensions,
        limit=limit,
        connection_id=conn["id"],
        source_type="git",
    )


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
        return _list_git_files(conn, filt, extensions=extensions, limit=limit)
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
        root = ensure_git_checkout(conn)
        src = root / rel
        if not src.is_file():
            raise FileNotFoundError(f"Not found in git checkout: {rel}")
        shutil.copy2(src, dest)
        digest = sha256_file(dest)
        return {"name": name, "sha256": digest, "dest": str(dest)}
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
