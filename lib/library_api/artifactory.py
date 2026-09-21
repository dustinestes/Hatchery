"""Artifactory Library API adapter (#255).

Filter grammar (binding filter): ``repoKey[/path/glob]``

Examples: ``media-isos/**/*.iso``, ``scripts/automation/*.ps1``, ``clutches``.

Base URI is the Artifactory root (e.g. ``https://host/artifactory``).
Optional token is sent as ``Authorization: Bearer …``.
"""

from __future__ import annotations

import json
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from lib.library_api.base import BaseLibraryApiAdapter

_TIMEOUT_S = 30
_DOWNLOAD_TIMEOUT_S = 120


class ArtifactoryAdapter(BaseLibraryApiAdapter):
    id = "artifactory"
    title = "Artifactory"
    description = (
        "JFrog Artifactory (or compatible) artifact repository - filter is repoKey[/path/glob]."
    )

    def test(self, conn: dict[str, Any]) -> dict[str, Any]:
        base = _base_uri(conn)
        url = f"{base}/api/system/ping"
        try:
            code, body = _http_text("GET", url, token=conn.get("token") or "", timeout=15)
        except _ApiError as exc:
            return {"ok": False, "message": str(exc)}
        if code != 200:
            return {"ok": False, "message": f"Artifactory ping HTTP {code}: {body[:200]}"}
        display = (conn.get("base_uri") or "").strip()
        return {"ok": True, "message": f"Artifactory OK: {display}"}

    def list_hits(
        self,
        conn: dict[str, Any],
        filt: str,
        *,
        extensions: frozenset[str],
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        repo, pattern = _parse_filter(filt)
        base = _base_uri(conn)
        token = conn.get("token") or ""
        cid = str(conn.get("id") or "")

        # Prefer AQL for glob-style filters; fall back to storage walk.
        try:
            rows = _aql_files(base, token, repo=repo, pattern=pattern, extensions=extensions)
        except _ApiError:
            rows = _storage_walk(
                base, token, repo=repo, pattern=pattern, extensions=extensions, limit=limit
            )

        hits: list[dict[str, Any]] = []
        for row in rows:
            rel = row["relative_path"]
            name = Path(rel).name
            if Path(name).suffix.lower() not in extensions:
                continue
            if not _match_repo_path(rel, repo, pattern):
                continue
            hits.append(
                {
                    "name": name,
                    "relative_path": rel,
                    "sha256": row.get("sha256"),
                    "connection_id": cid,
                    "source_type": "api",
                }
            )
            if limit is not None and len(hits) >= limit:
                break
        hits.sort(key=lambda h: h["name"].lower())
        return hits

    def pull_file(
        self,
        conn: dict[str, Any],
        relative_path: str,
        dest: Path,
    ) -> dict[str, Any]:
        rel = relative_path.replace("\\", "/").lstrip("/")
        if ".." in Path(rel).parts:
            raise ValueError("Invalid relative path")
        name = Path(rel).name
        base = _base_uri(conn)
        token = conn.get("token") or ""
        # relative_path is repoKey/path/to/file
        download_url = f"{base}/{quote(rel, safe='/')}"
        sha_header: str | None = None
        try:
            req = _request("GET", download_url, token=token)
            with urlopen(req, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
                sha_header = (
                    resp.headers.get("X-Checksum-Sha256")
                    or resp.headers.get("X-Checksum-Sha2")
                    or None
                )
                with open(dest, "wb") as out:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
        except HTTPError as exc:
            dest.unlink(missing_ok=True)
            raise ValueError(f"Artifactory download HTTP {exc.code}: {exc.reason}") from exc
        except (URLError, OSError, TimeoutError) as exc:
            dest.unlink(missing_ok=True)
            raise ValueError(f"Artifactory download failed: {exc}") from exc

        from lib.library import sha256_file

        digest = (sha_header or "").strip().lower() or sha256_file(dest)
        return {"name": name, "sha256": digest, "dest": str(dest)}

    def source_digest(self, conn: dict[str, Any], relative_path: str) -> tuple[str, str] | None:
        """Return ``(sha256, digest)`` from Storage API metadata — no artifact download."""
        rel = relative_path.replace("\\", "/").lstrip("/")
        if not rel or ".." in Path(rel).parts:
            return None
        try:
            base = _base_uri(conn)
            token = conn.get("token") or ""
            url = f"{base}/api/storage/{quote(rel, safe='/')}"
            code, body = _http_text("GET", url, token=token, timeout=_TIMEOUT_S)
            if code != 200:
                return None
            data = json.loads(body)
        except (_ApiError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        checksums = data.get("checksums") or {}
        if isinstance(checksums, dict):
            sha = (checksums.get("sha256") or "").strip().lower()
            if sha:
                return ("sha256", sha)
        return None


class _ApiError(Exception):
    """HTTP / parse failure for Artifactory calls."""


def _base_uri(conn: dict[str, Any]) -> str:
    raw = str(conn.get("base_uri") or "").strip().rstrip("/")
    if not raw:
        raise _ApiError("Artifactory base URI is required")
    if not raw.startswith(("http://", "https://")):
        raise _ApiError("Artifactory base URI must be an http(s) URL")
    return raw


def _parse_filter(filt: str) -> tuple[str, str]:
    """Split ``repoKey[/glob]`` into repo and path pattern (default ``**/*``)."""
    text = (filt or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if not text or text == "*":
        raise ValueError(
            "Artifactory filter needs a repository key (e.g. media-isos/**/*.iso or scripts/*.ps1)"
        )
    if "/" not in text:
        return text, "**/*"
    repo, rest = text.split("/", 1)
    repo = repo.strip()
    rest = rest.strip() or "**/*"
    if not repo:
        raise ValueError("Artifactory filter repository key is empty")
    return repo, rest


def _match_repo_path(relative_path: str, repo: str, pattern: str) -> bool:
    """``relative_path`` is ``repo/…``; match ``pattern`` against path inside the repo."""
    prefix = f"{repo}/"
    if not relative_path.startswith(prefix) and relative_path != repo:
        if relative_path.split("/", 1)[0] != repo:
            return False
    inner = relative_path[len(prefix) :] if relative_path.startswith(prefix) else ""
    if pattern in ("*", "**", "**/*"):
        return True
    if fnmatch(inner, pattern):
        return True
    if "/" not in pattern and fnmatch(Path(inner).name, pattern):
        return True
    return False


def _auth_headers(token: str) -> dict[str, str]:
    # Ping returns text/plain and rejects Accept: application/json (HTTP 406).
    # Storage/AQL still return JSON when asked with */*.
    headers = {"Accept": "*/*"}
    tok = (token or "").strip()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def _request(method: str, url: str, *, token: str, data: bytes | None = None) -> Request:
    headers = _auth_headers(token)
    if data is not None:
        headers["Content-Type"] = "text/plain"
    return Request(url, data=data, headers=headers, method=method)


def _http_text(
    method: str,
    url: str,
    *,
    token: str,
    timeout: int = _TIMEOUT_S,
    data: bytes | None = None,
) -> tuple[int, str]:
    try:
        req = _request(method, url, token=token, data=data)
        with urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
            return int(code), body
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(exc.reason)
        raise _ApiError(f"HTTP {exc.code}: {body[:200] or exc.reason}") from exc
    except URLError as exc:
        raise _ApiError(str(exc.reason if hasattr(exc, "reason") else exc)) from exc
    except TimeoutError as exc:
        raise _ApiError("request timed out") from exc


def _aql_files(
    base: str,
    token: str,
    *,
    repo: str,
    pattern: str,
    extensions: frozenset[str],
) -> list[dict[str, Any]]:
    """Query Artifacts via AQL; return rows with relative_path + optional sha256."""
    # Build a name match from extension set when pattern is broad.
    if pattern in ("*", "**", "**/*"):
        if len(extensions) == 1:
            ext = next(iter(extensions))
            criteria: dict[str, Any] = {
                "repo": repo,
                "type": "file",
                "name": {"$match": f"*{ext}"},
            }
        else:
            criteria = {
                "repo": repo,
                "type": "file",
                "$or": [{"name": {"$match": f"*{ext}"}} for ext in sorted(extensions)],
            }
    elif "/" not in pattern and ("*" in pattern or "?" in pattern):
        criteria = {"repo": repo, "type": "file", "name": {"$match": pattern}}
    else:
        # path + name from pattern when possible
        path_part = str(Path(pattern).parent).replace("\\", "/")
        name_part = Path(pattern).name
        criteria = {"repo": repo, "type": "file"}
        if path_part not in (".", "", "*"):
            if "*" in path_part or "?" in path_part:
                criteria["path"] = {"$match": path_part}
            else:
                criteria["path"] = path_part
        if name_part and name_part != "*":
            if "*" in name_part or "?" in name_part:
                criteria["name"] = {"$match": name_part}
            else:
                criteria["name"] = name_part

    query = (
        f'items.find({json.dumps(criteria)}).include("name","repo","path","actual_sha2","sha256")'
    )
    url = f"{base}/api/search/aql"
    code, body = _http_text("POST", url, token=token, data=query.encode("utf-8"))
    if code != 200:
        raise _ApiError(f"AQL HTTP {code}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise _ApiError("AQL response was not JSON") from exc
    results = payload.get("results") or []
    rows: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        path = str(item.get("path") or "").strip("/")
        if path in (".", ""):
            rel = f"{repo}/{name}"
        else:
            rel = f"{repo}/{path}/{name}"
        sha = item.get("actual_sha2") or item.get("sha256") or None
        if isinstance(sha, str):
            sha = sha.strip().lower() or None
        else:
            sha = None
        rows.append({"relative_path": rel, "sha256": sha})
    return rows


def _storage_walk(
    base: str,
    token: str,
    *,
    repo: str,
    pattern: str,
    extensions: frozenset[str],
    limit: int | None,
) -> list[dict[str, Any]]:
    """Recursively list via Storage API (fallback when AQL unavailable)."""
    rows: list[dict[str, Any]] = []
    stack = [""]
    while stack:
        sub = stack.pop()
        url = f"{base}/api/storage/{quote(repo, safe='')}"
        if sub:
            url = f"{url}/{quote(sub, safe='/')}"
        code, body = _http_text("GET", url, token=token)
        if code != 200:
            raise _ApiError(f"storage HTTP {code}")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise _ApiError("storage response was not JSON") from exc
        children = payload.get("children") or []
        # File info endpoint (leaf) has checksums, no children
        if not children and payload.get("checksums"):
            path = str(payload.get("path") or "").strip("/")
            # path like /repo/foo/bar.iso or /foo/bar.iso depending on version
            rel = _normalize_storage_path(repo, path, str(payload.get("uri") or ""))
            sha = None
            checksums = payload.get("checksums") or {}
            if isinstance(checksums, dict):
                sha = (checksums.get("sha256") or "").strip().lower() or None
            rows.append({"relative_path": rel, "sha256": sha})
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            uri = str(child.get("uri") or "").lstrip("/")
            if not uri:
                continue
            child_path = f"{sub}/{uri}".strip("/") if sub else uri
            if child.get("folder"):
                stack.append(child_path)
                continue
            name = Path(uri).name
            if Path(name).suffix.lower() not in extensions:
                continue
            rel = f"{repo}/{child_path}"
            if not _match_repo_path(rel, repo, pattern):
                continue
            rows.append({"relative_path": rel, "sha256": None})
            if limit is not None and len(rows) >= limit:
                return rows
    return rows


def _normalize_storage_path(repo: str, path: str, uri: str) -> str:
    path = path.strip("/")
    if path.startswith(f"{repo}/"):
        return path
    if path:
        return f"{repo}/{path}"
    uri = uri.strip("/")
    if uri:
        return f"{repo}/{uri}" if not uri.startswith(repo) else uri
    return repo
