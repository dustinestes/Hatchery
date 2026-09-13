"""Library connections and domain bindings — list, test, and pull into the operator cache.

v1 focuses on ``path`` connections (local or mounted share). ``https`` supports
reachability tests and pulling a single relative file. ``git`` is accepted in
Settings for forward compatibility; test/list/pull return a clear not-implemented
message until a later issue.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from datetime import date, timedelta
from fnmatch import fnmatch
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lib.import_files import SCRIPT_EXTENSIONS

CONNECTION_TYPES = frozenset({"path", "https", "git"})
CONNECTION_KINDS = frozenset({"scripts", "clutches", "media", "packages"})
_SAMPLE_LIMIT = 5
_PULL_DEST = "automation/scripts"


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
        out.append(
            {
                "id": cid,
                "label": label,
                "type": ctype,
                "base_uri": base_uri,
                "token": token,
                "expires_at": expires_at,
                "kinds": kinds,
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
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("script bindings must be a list")
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
            raise ValueError("script binding references an unknown connection")
        conn = by_id[conn_id]
        if "scripts" not in conn["kinds"]:
            raise ValueError(
                f"connection '{conn['label']}' does not serve scripts — "
                "enable the scripts kind on the connection"
            )
        filt = str(item.get("filter") or "").strip() or "*"
        out.append({"id": bid, "connection_id": conn_id, "filter": filt, "domain": "scripts"})
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
        return {
            "ok": False,
            "message": "Git connections are saved but test/list/pull land in a follow-on — use path for now.",
        }
    return {"ok": False, "message": f"Unsupported type: {ctype}"}


def os_access_dir(path: Path) -> bool:
    try:
        next(path.iterdir(), None)
        return True
    except OSError:
        return False


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
    """List script files for a connection + filter.

    Each hit: {name, relative_path, sha256?, connection_id, binding filter context}.
    """
    ctype = conn["type"]
    if ctype == "path":
        return _list_path_scripts(conn, filt, limit=limit)
    if ctype == "https":
        return _list_https_scripts(conn, filt, limit=limit)
    if ctype == "git":
        raise ValueError("Git list/pull is not implemented yet — use a path connection")
    raise ValueError(f"Unsupported connection type: {ctype}")


def _normalize_filter(filt: str) -> str:
    f = (filt or "*").strip().replace("\\", "/")
    while f.startswith("./"):
        f = f[2:]
    return f or "*"


def _list_path_scripts(conn: dict, filt: str, *, limit: int | None) -> list[dict]:
    root = _expand_base(conn["base_uri"])
    if not root.is_dir():
        raise ValueError(f"Connection path is not a directory: {root}")
    pattern = _normalize_filter(filt)
    hits: list[dict] = []
    # If pattern has no slash and no glob, treat as filename under root.
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SCRIPT_EXTENSIONS:
            continue
        rel = path.relative_to(root).as_posix()
        if not _match_filter(rel, pattern):
            continue
        hits.append(
            {
                "name": path.name,
                "relative_path": rel,
                "sha256": sha256_file(path),
                "connection_id": conn["id"],
                "source_type": "path",
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
    # Also allow matching on basename only.
    if "/" not in pattern and fnmatch(Path(relative_path).name, pattern):
        return True
    return False


def _list_https_scripts(conn: dict, filt: str, *, limit: int | None) -> list[dict]:
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
        if Path(name).suffix.lower() not in SCRIPT_EXTENSIONS:
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


def test_filter(conn: dict, filt: str) -> dict:
    """Return {ok, message, hits} with up to _SAMPLE_LIMIT matches."""
    try:
        hits = list_script_hits(conn, filt, limit=_SAMPLE_LIMIT)
    except ValueError as exc:
        return {"ok": False, "message": str(exc), "hits": []}
    if not hits:
        return {
            "ok": True,
            "message": "Connected, but no script files matched this filter (sample limit "
            f"{_SAMPLE_LIMIT}).",
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
) -> dict:
    """Copy one script into the operator automation/scripts cache (create-only).

    Returns {name, sha256, dest}.
    """
    from lib import config as config_lib

    rel = relative_path.replace("\\", "/").lstrip("/")
    if ".." in Path(rel).parts:
        raise ValueError("Invalid relative path")
    name = Path(rel).name
    if Path(name).suffix.lower() not in SCRIPT_EXTENSIONS:
        raise ValueError(f"Unsupported script type: {name}")

    dest_root = dest_dir or (config_lib.data_dir() / _PULL_DEST)
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / name
    if dest.exists():
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
            with urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
                shutil.copyfileobj(resp, out)
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        digest = sha256_file(dest)
        return {"name": name, "sha256": digest, "dest": str(dest)}
    raise ValueError(f"Pull not supported for type: {ctype}")


def catalog_scripts(connections: list[dict], bindings: list[dict]) -> list[dict]:
    """Union of script hits across all Scripts bindings (dedupe by name, first wins)."""
    by_id = {c["id"]: c for c in connections}
    seen_names: set[str] = set()
    out: list[dict] = []
    for binding in bindings:
        conn = by_id.get(binding["connection_id"])
        if not conn:
            continue
        try:
            hits = list_script_hits(conn, binding.get("filter") or "*", limit=None)
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
