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
        "GitHub.com repositories via Trees/Contents APIs - no Controller clone. "
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
                "GitHub tree is truncated - narrow the binding filter or use a smaller repo"
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
        import base64

        from lib.library import git_blob_sha_bytes, sha256_file

        rel = relative_path.replace("\\", "/").lstrip("/")
        if not rel or ".." in Path(rel).parts:
            raise ValueError("Invalid relative path")
        name = Path(rel).name
        owner, repo = parse_github_repo(conn.get("base_uri") or "")
        token = conn.get("token") or ""
        branch = _default_branch(owner, repo, token)
        # Prefer Contents API (blob sha + body) over raw.githubusercontent.com CDN,
        # which can return stale bytes after the Trees tip already advanced.
        meta_url = (
            f"{_API}/repos/{quote(owner)}/{quote(repo)}/contents/"
            f"{quote(rel, safe='/')}?ref={quote(branch, safe='')}"
        )
        try:
            code, data = _http_json("GET", meta_url, token=token, timeout=_TIMEOUT_S)
        except _ForgeError as exc:
            raise ValueError(f"GitHub contents failed: {exc}") from exc
        if code != 200 or not isinstance(data, dict):
            raise ValueError(f"GitHub contents HTTP {code}: {_err_body(data)}")
        expected_blob = str(data.get("sha") or "").strip().lower()
        encoding = str(data.get("encoding") or "").strip().lower()
        raw: bytes
        if encoding == "base64" and data.get("content"):
            try:
                raw = base64.b64decode(data["content"])
            except (ValueError, TypeError) as exc:
                raise ValueError("GitHub contents payload was not valid base64") from exc
        else:
            download_url = str(data.get("download_url") or "").strip()
            if not download_url:
                raise ValueError("GitHub contents response missing file body")
            try:
                req = _request("GET", download_url, token=token, accept="*/*")
                with urlopen(req, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
                    chunks: list[bytes] = []
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        chunks.append(chunk)
                raw = b"".join(chunks)
            except HTTPError as exc:
                raise ValueError(f"GitHub download HTTP {exc.code}: {exc.reason}") from exc
            except URLError as exc:
                raise ValueError(f"GitHub download failed: {exc.reason}") from exc
        if expected_blob:
            actual_blob = git_blob_sha_bytes(raw)
            if actual_blob != expected_blob:
                raise ValueError(
                    "GitHub download does not match Contents blob sha "
                    f"(got {actual_blob[:12]}…, expected {expected_blob[:12]}…)"
                )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        digest = sha256_file(dest)
        return {"name": name, "sha256": digest, "dest": str(dest)}

    def tip_index(self, conn: dict[str, Any]) -> dict[str, tuple[str, str]]:
        """One Trees fetch → ``{relative_path: (git_blob, sha)}`` for the default branch.

        Raises ``LibraryRateLimitError`` on GitHub 403/429.
        """
        from lib.library import LibraryRateLimitError

        owner, repo = parse_github_repo(conn.get("base_uri") or "")
        token = conn.get("token") or ""
        try:
            branch = _default_branch(owner, repo, token)
            url = (
                f"{_API}/repos/{quote(owner)}/{quote(repo)}/git/trees/"
                f"{quote(branch, safe='')}?recursive=1"
            )
            code, data = _http_json("GET", url, token=token, timeout=_TIMEOUT_S)
        except _ForgeError as exc:
            raise LibraryRateLimitError(str(exc)) from exc
        if code in (403, 429):
            raise LibraryRateLimitError(f"GitHub HTTP {code}: {_err_body(data)}")
        if code != 200 or not isinstance(data, dict) or data.get("truncated"):
            return {}
        out: dict[str, tuple[str, str]] = {}
        for entry in data.get("tree") or []:
            if entry.get("type") != "blob":
                continue
            rel = str(entry.get("path") or "").replace("\\", "/")
            if not rel or ".." in Path(rel).parts:
                continue
            sha = str(entry.get("sha") or "").strip().lower()
            if sha:
                out[rel] = ("git_blob", sha)
        return out

    def source_digest_one(self, conn: dict[str, Any], relative_path: str) -> tuple[str, str] | None:
        """Cheap one-path tip via Contents API metadata (no body download)."""
        from lib.library import LibraryRateLimitError

        rel = relative_path.replace("\\", "/").lstrip("/")
        if not rel or ".." in Path(rel).parts:
            return None
        try:
            owner, repo = parse_github_repo(conn.get("base_uri") or "")
        except ValueError:
            return None
        token = conn.get("token") or ""
        try:
            branch = _default_branch(owner, repo, token)
            meta_url = (
                f"{_API}/repos/{quote(owner)}/{quote(repo)}/contents/"
                f"{quote(rel, safe='/')}?ref={quote(branch, safe='')}"
            )
            code, data = _http_json("GET", meta_url, token=token, timeout=_TIMEOUT_S)
        except _ForgeError:
            return None
        if code in (403, 429):
            raise LibraryRateLimitError(f"GitHub HTTP {code}: {_err_body(data)}")
        if code != 200 or not isinstance(data, dict):
            return None
        sha = str(data.get("sha") or "").strip().lower()
        if sha:
            return ("git_blob", sha)
        return None

    def source_digest(self, conn: dict[str, Any], relative_path: str) -> tuple[str, str] | None:
        """Return ``(git_blob, sha)`` — prefers Contents for one path; else Trees index."""
        one = self.source_digest_one(conn, relative_path)
        if one is not None:
            return one
        rel = relative_path.replace("\\", "/").lstrip("/")
        return self.tip_index(conn).get(rel)


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
