"""GitHub Library forge adapter (#307).

Filter grammar (binding filter): path glob relative to the repository root
(default branch). Examples: ``*.ps1``, ``scripts/**/*.ps1``, ``clutches/*.yaml``.

Base URI: ``https://github.com/owner/repo`` (optional ``.git`` suffix).
Optional token is sent as ``Authorization: Bearer …`` (fine-grained or classic PAT).
"""

from __future__ import annotations

import json
import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from lib.library_forge.base import BaseLibraryForgeAdapter

_TIMEOUT_S = 30
_DOWNLOAD_TIMEOUT_S = 120
_API = "https://api.github.com"


class _ForgeError(Exception):
    pass


class GitHubAdapter(BaseLibraryForgeAdapter):
    id = "github"
    title = "GitHub"
    description = (
        "GitHub.com repositories via Trees/Contents APIs — no Controller clone. "
        "Filter is a path glob under the default branch."
    )

    def test(self, conn: dict[str, Any]) -> dict[str, Any]:
        try:
            owner, repo = parse_github_repo(conn.get("base_uri") or "")
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}
        url = f"{_API}/repos/{quote(owner)}/{quote(repo)}"
        try:
            code, data = _http_json("GET", url, token=conn.get("token") or "", timeout=15)
        except _ForgeError as exc:
            return {"ok": False, "message": str(exc)}
        if code == 404:
            return {"ok": False, "message": f"Repository not found: {owner}/{repo}"}
        if code != 200:
            return {"ok": False, "message": f"GitHub HTTP {code}: {_err_body(data)}"}
        full = data.get("full_name") or f"{owner}/{repo}"
        branch = data.get("default_branch") or "main"
        return {"ok": True, "message": f"GitHub OK: {full} (default branch {branch})"}

    def list_hits(
        self,
        conn: dict[str, Any],
        filt: str,
        *,
        extensions: frozenset[str],
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        owner, repo = parse_github_repo(conn.get("base_uri") or "")
        token = conn.get("token") or ""
        cid = str(conn.get("id") or "")
        pattern = _normalize_filter(filt)
        branch = _default_branch(owner, repo, token)

        url = (
            f"{_API}/repos/{quote(owner)}/{quote(repo)}/git/trees/"
            f"{quote(branch, safe='')}?recursive=1"
        )
        code, data = _http_json("GET", url, token=token, timeout=_TIMEOUT_S)
        if code != 200:
            raise ValueError(f"GitHub tree HTTP {code}: {_err_body(data)}")
        if data.get("truncated"):
            raise ValueError(
                "GitHub tree is truncated — narrow the binding filter or use a smaller repo"
            )

        hits: list[dict[str, Any]] = []
        for entry in data.get("tree") or []:
            if entry.get("type") != "blob":
                continue
            rel = str(entry.get("path") or "").replace("\\", "/")
            if not rel or ".." in Path(rel).parts:
                continue
            name = Path(rel).name
            if Path(name).suffix.lower() not in extensions:
                continue
            if not _match_filter(rel, pattern):
                continue
            hits.append(
                {
                    "name": name,
                    "relative_path": rel,
                    "sha256": None,
                    "connection_id": cid,
                    "source_type": "forge",
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
        from lib.library import sha256_file

        rel = relative_path.replace("\\", "/").lstrip("/")
        if not rel or ".." in Path(rel).parts:
            raise ValueError("Invalid relative path")
        name = Path(rel).name
        owner, repo = parse_github_repo(conn.get("base_uri") or "")
        token = conn.get("token") or ""
        branch = _default_branch(owner, repo, token)
        raw_url = (
            f"https://raw.githubusercontent.com/{quote(owner)}/{quote(repo)}/"
            f"{quote(branch, safe='')}/{quote(rel, safe='/')}"
        )
        try:
            req = _request("GET", raw_url, token=token, accept="*/*")
            with urlopen(req, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
                with open(dest, "wb") as out:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
        except HTTPError as exc:
            dest.unlink(missing_ok=True)
            raise ValueError(f"GitHub download HTTP {exc.code}: {exc.reason}") from exc
        except URLError as exc:
            dest.unlink(missing_ok=True)
            raise ValueError(f"GitHub download failed: {exc.reason}") from exc
        digest = sha256_file(dest)
        return {"name": name, "sha256": digest, "dest": str(dest)}


def parse_github_repo(base_uri: str) -> tuple[str, str]:
    """Return ``(owner, repo)`` from a GitHub HTTPS or ``owner/repo`` URI."""
    uri = (base_uri or "").strip()
    if not uri:
        raise ValueError("GitHub connection needs a repository URL")
    if uri.endswith(".git"):
        uri = uri[:-4]
    # Plain owner/repo
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", uri):
        owner, repo = uri.split("/", 1)
        return owner, repo
    parsed = urlparse(uri)
    host = (parsed.hostname or "").lower()
    if host not in ("github.com", "www.github.com"):
        raise ValueError(
            f"GitHub provider expects github.com URL or owner/repo (got host {host or '(none)'})"
        )
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) < 2:
        raise ValueError("GitHub URL must include owner and repository")
    return parts[0], parts[1]


def _default_branch(owner: str, repo: str, token: str) -> str:
    url = f"{_API}/repos/{quote(owner)}/{quote(repo)}"
    code, data = _http_json("GET", url, token=token, timeout=15)
    if code != 200:
        raise ValueError(f"GitHub repo HTTP {code}: {_err_body(data)}")
    branch = str(data.get("default_branch") or "").strip()
    return branch or "main"


def _normalize_filter(filt: str) -> str:
    f = (filt or "*").strip().replace("\\", "/")
    while f.startswith("./"):
        f = f[2:]
    return f or "*"


def _match_filter(rel: str, pattern: str) -> bool:
    if pattern == "*":
        return True
    if fnmatch(rel, pattern):
        return True
    # basename-only patterns
    if "/" not in pattern.rstrip("/") and fnmatch(Path(rel).name, pattern):
        return True
    return False


def _err_body(data: Any) -> str:
    if isinstance(data, dict):
        msg = data.get("message")
        if msg:
            return str(msg)[:200]
    return str(data)[:200]


def _request(
    method: str, url: str, *, token: str, accept: str = "application/vnd.github+json"
) -> Request:
    req = Request(url, method=method)
    req.add_header("Accept", accept)
    req.add_header("User-Agent", "Hatchery-Library-Forge")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    tok = (token or "").strip()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    return req


def _http_json(
    method: str,
    url: str,
    *,
    token: str,
    timeout: float,
) -> tuple[int, Any]:
    try:
        req = _request(method, url, token=token)
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = getattr(resp, "status", None) or resp.getcode()
            if not raw:
                return int(code), {}
            try:
                return int(code), json.loads(raw)
            except json.JSONDecodeError:
                return int(code), {"message": raw[:200]}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            data = json.loads(body) if body else {"message": exc.reason}
        except json.JSONDecodeError:
            data = {"message": body[:200] or str(exc.reason)}
        return int(exc.code), data
    except URLError as exc:
        raise _ForgeError(f"GitHub request failed: {exc.reason}") from exc
