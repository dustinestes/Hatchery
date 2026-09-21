"""Import uploaded files into Hatchery data-directory subtrees (create-only)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import BinaryIO

from lib import alerts as alerts_lib
from lib import config

# Must stay aligned with hatchery._SCRIPT_LANGUAGES keys.
SCRIPT_EXTENSIONS = frozenset({".ps1", ".sh", ".bash", ".py", ".bat", ".cmd"})

_KINDS: dict[str, dict] = {
    "clutches": {
        "subdir": "clutches",
        "extensions": frozenset({".yaml"}),
    },
    "media/iso": {
        "subdir": "media/iso",
        "extensions": frozenset({".iso"}),
    },
    "media/virtio": {
        "subdir": "media/virtio",
        "extensions": frozenset({".iso"}),
    },
    "automation/scripts": {
        "subdir": "automation/scripts",
        "extensions": SCRIPT_EXTENSIONS,
    },
}

_IN_PROGRESS_PREFIX = "Import in progress:"
_FINISHED_PREFIX = "Import finished:"


def known_kinds() -> list[str]:
    """Return supported import kind keys."""
    return list(_KINDS)


def _safe_basename(filename: str | None) -> str | None:
    if not filename:
        return None
    safe = Path(filename).name
    if not safe or safe in (".", ".."):
        return None
    return safe


def _dest_root(subdir: str) -> Path:
    root = (config.data_dir() / subdir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_dest(root: Path, name: str) -> Path | None:
    candidate = (root / name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _write_create_only(dest: Path, stream: BinaryIO) -> None:
    """Write stream to dest; raise FileExistsError if the path already exists."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(dest, flags, 0o644)
    try:
        with os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(stream, out)
    except Exception:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def import_uploads(kind: str, files: list) -> dict:
    """Import Werkzeug FileStorage-like objects into the data dir for ``kind``.

    Each item must expose ``.filename`` and ``.stream`` (or be file-like with a
    ``filename`` attribute). Returns ``{"imported": [...], "errors": [...]}``.
    """
    if kind not in _KINDS:
        raise ValueError(f"unsupported import kind: {kind}")

    spec = _KINDS[kind]
    subdir: str = spec["subdir"]
    allowed: frozenset[str] = spec["extensions"]
    root = _dest_root(subdir)

    pending: list[tuple[str, object]] = []
    errors: list[dict] = []
    for f in files:
        raw_name = getattr(f, "filename", None)
        safe = _safe_basename(raw_name)
        if safe is None:
            errors.append({"name": raw_name or "", "reason": "invalid filename"})
            continue
        ext = Path(safe).suffix.lower()
        if ext not in allowed:
            errors.append(
                {
                    "name": safe,
                    "reason": f"unsupported file type (allowed: {', '.join(sorted(allowed))})",
                }
            )
            continue
        dest = _resolve_dest(root, safe)
        if dest is None:
            errors.append({"name": safe, "reason": "invalid filename"})
            continue
        if dest.exists():
            errors.append({"name": safe, "reason": "already exists (refuse overwrite)"})
            continue
        pending.append((safe, f))

    imported: list[str] = []
    in_progress_id: int | None = None
    in_progress_msg = f"{_IN_PROGRESS_PREFIX} {len(pending)} file(s) into {subdir}/"

    if pending:
        if not alerts_lib.has_active_alert(in_progress_msg):
            in_progress_id = alerts_lib.record_alert(in_progress_msg, tier="info")
        for name, upload in pending:
            dest = _resolve_dest(root, name)
            assert dest is not None
            if dest.exists():
                errors.append({"name": name, "reason": "already exists (refuse overwrite)"})
                continue
            try:
                stream = getattr(upload, "stream", upload)
                _write_create_only(dest, stream)
            except FileExistsError:
                errors.append({"name": name, "reason": "already exists (refuse overwrite)"})
            except OSError as exc:
                errors.append({"name": name, "reason": str(exc)})
            else:
                imported.append(name)

        if in_progress_id is not None:
            alerts_lib.resolve(in_progress_id)
        else:
            alerts_lib.resolve_alerts_by_prefix(in_progress_msg)

        n_ok = len(imported)
        n_err = len(errors)
        if n_ok and not n_err:
            finished = f"{_FINISHED_PREFIX} {n_ok} imported into {subdir}/ - ready to use"
            finished_tier = "info"
        elif n_ok:
            finished = (
                f"{_FINISHED_PREFIX} {n_ok} imported, {n_err} skipped into {subdir}/ - ready to use"
            )
            finished_tier = "warning"
        else:
            finished = f"{_FINISHED_PREFIX} with errors: 0 imported into {subdir}/"
            finished_tier = "warning"
        finished_id = alerts_lib.record_alert(finished, tier=finished_tier)
        alerts_lib.resolve(finished_id)

    return {"imported": imported, "errors": errors}
