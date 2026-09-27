"""Import uploaded files into Hatchery data-directory subtrees (create-only)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import BinaryIO

from lib import alerts as alerts_lib
from lib import config
from lib import software as software_lib

# Must stay aligned with hatchery._SCRIPT_LANGUAGES keys.
SCRIPT_EXTENSIONS = frozenset({".ps1", ".sh", ".bash", ".py", ".bat", ".cmd"})

# Answer-file templates (#177): XML/Jinja, YAML, companions, plain text.
ANSWERFILE_EXTENSIONS = frozenset({".xml", ".j2", ".yml", ".yaml", ".ps1", ".cfg", ".txt"})

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
    "automation/answerfiles": {
        "subdir": "automation/answerfiles",
        "extensions": ANSWERFILE_EXTENSIONS,
    },
}

_IN_PROGRESS_PREFIX = "Import in progress:"
_FINISHED_PREFIX = "Import finished:"
_SOFTWARE_KIND = "automation/software"
_SOFTWARE_SUBDIR = software_lib.SUBDIR
_DEFINITION = software_lib.DEFINITION_FILENAME


def known_kinds() -> list[str]:
    """Return supported import kind keys (includes Software tree import)."""
    return [*_KINDS, _SOFTWARE_KIND]


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


def _finish_import_alerts(
    *,
    subdir: str,
    pending_count: int,
    imported: list[str],
    errors: list[dict],
    in_progress_id: int | None,
    in_progress_msg: str,
) -> None:
    if pending_count == 0:
        return
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


def _normalize_rel_path(raw: str | None) -> str | None:
    """Return a safe POSIX relative path, or None if invalid / escaping."""
    if not raw or not str(raw).strip():
        return None
    text = str(raw).replace("\\", "/").strip().lstrip("/")
    if not text or text in (".", ".."):
        return None
    parts = Path(text).parts
    if any(p in ("", ".", "..") for p in parts):
        return None
    if Path(text).is_absolute():
        return None
    return Path(*parts).as_posix()


def _is_package_id(name: str) -> bool:
    """Folder id must look like Publisher.Product.Version (at least two dots)."""
    if not name or name in (".", "..") or Path(name).name != name:
        return False
    return name.count(".") >= 2


def _package_roots_from_paths(rel_paths: list[str]) -> list[str]:
    """Dirs that contain ``software.yaml`` as an immediate child."""
    roots: set[str] = set()
    for rel in rel_paths:
        parts = Path(rel).parts
        if not parts or parts[-1] != _DEFINITION:
            continue
        if len(parts) < 2:
            # Bare software.yaml with no package folder - cannot derive id.
            continue
        roots.add(Path(*parts[:-1]).as_posix())
    return sorted(roots)


def import_software_tree(files: list) -> dict:
    """Import Software package directories from a folder-picker upload (#469).

    Each item must expose ``.filename`` as a **relative path** within the selected
    tree (browser ``webkitRelativePath``) and ``.stream``. Classifies:

    - Package root: path ``{id}/software.yaml`` (and siblings) → import ``{id}``
    - Parent of packages: multiple such roots → batch import each
    - Otherwise (e.g. only ``windows/…``): error asking for a package folder

    Package id = basename of the package root. Create-only refuse overwrite.
    """
    errors: list[dict] = []
    entries: list[tuple[str, object]] = []
    for f in files:
        raw_name = getattr(f, "filename", None)
        rel = _normalize_rel_path(raw_name)
        if rel is None:
            errors.append({"name": raw_name or "", "reason": "invalid relative path"})
            continue
        entries.append((rel, f))

    if not entries and errors:
        return {"imported": [], "errors": errors}
    if not entries:
        return {
            "imported": [],
            "errors": [
                {
                    "name": "",
                    "reason": (
                        "Select a Software package folder (must contain software.yaml), "
                        "or a parent folder of one or more packages"
                    ),
                }
            ],
        }

    roots = _package_roots_from_paths([rel for rel, _ in entries])
    if not roots:
        return {
            "imported": [],
            "errors": [
                {
                    "name": "",
                    "reason": (
                        "Select a Software package folder (must contain software.yaml), "
                        "or a parent folder of one or more packages. "
                        "Do not select windows/, linux/, or macos/ alone"
                    ),
                }
            ],
        }

    root = _dest_root(_SOFTWARE_SUBDIR)
    pending: list[tuple[str, str, list[tuple[str, object]]]] = []
    # (package_id, package_root_prefix, [(rel_within_package, upload), ...])
    for pkg_root in roots:
        package_id = Path(pkg_root).name
        if not _is_package_id(package_id):
            errors.append(
                {
                    "name": package_id,
                    "reason": "package folder must be Publisher.Product.Version",
                }
            )
            continue
        dest = _resolve_dest(root, package_id)
        if dest is None:
            errors.append({"name": package_id, "reason": "invalid package id"})
            continue
        if dest.exists():
            errors.append({"name": package_id, "reason": "already exists (refuse overwrite)"})
            continue
        members: list[tuple[str, object]] = []
        prefix = pkg_root + "/"
        for rel, upload in entries:
            if rel == pkg_root:
                continue
            if not rel.startswith(prefix):
                continue
            within = rel[len(prefix) :]
            within_n = _normalize_rel_path(within)
            if within_n is None:
                errors.append({"name": rel, "reason": "invalid relative path"})
                continue
            members.append((within_n, upload))
        if not any(m == _DEFINITION for m, _ in members):
            errors.append(
                {
                    "name": package_id,
                    "reason": "package root must contain software.yaml",
                }
            )
            continue
        pending.append((package_id, pkg_root, members))

    imported: list[str] = []
    in_progress_id: int | None = None
    in_progress_msg = f"{_IN_PROGRESS_PREFIX} {len(pending)} package(s) into {_SOFTWARE_SUBDIR}/"

    if pending:
        if not alerts_lib.has_active_alert(in_progress_msg):
            in_progress_id = alerts_lib.record_alert(in_progress_msg, tier="info")
        for package_id, _pkg_root, members in pending:
            dest = _resolve_dest(root, package_id)
            assert dest is not None
            if dest.exists():
                errors.append({"name": package_id, "reason": "already exists (refuse overwrite)"})
                continue
            staging = root / f".importing-{package_id}"
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            try:
                staging.mkdir(parents=False, exist_ok=False)
                for within, upload in members:
                    target = (staging / within).resolve()
                    try:
                        target.relative_to(staging.resolve())
                    except ValueError:
                        raise ValueError(f"unsafe path: {within}") from None
                    target.parent.mkdir(parents=True, exist_ok=True)
                    stream = getattr(upload, "stream", upload)
                    _write_create_only(target, stream)
                if not (staging / _DEFINITION).is_file():
                    raise ValueError("package root must contain software.yaml")
                staging.rename(dest)
            except (OSError, ValueError, FileExistsError) as exc:
                shutil.rmtree(staging, ignore_errors=True)
                errors.append({"name": package_id, "reason": str(exc)})
            else:
                imported.append(package_id)

        _finish_import_alerts(
            subdir=_SOFTWARE_SUBDIR,
            pending_count=len(pending),
            imported=imported,
            errors=errors,
            in_progress_id=in_progress_id,
            in_progress_msg=in_progress_msg,
        )

    return {"imported": imported, "errors": errors}


def import_uploads(kind: str, files: list) -> dict:
    """Import Werkzeug FileStorage-like objects into the data dir for ``kind``.

    Each item must expose ``.filename`` and ``.stream`` (or be file-like with a
    ``filename`` attribute). Returns ``{"imported": [...], "errors": [...]}``.

    For ``automation/software``, see :func:`import_software_tree` (directory
    picker with relative paths - not single-file / zip).
    """
    if kind == _SOFTWARE_KIND:
        return import_software_tree(files)

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

        _finish_import_alerts(
            subdir=subdir,
            pending_count=len(pending),
            imported=imported,
            errors=errors,
            in_progress_id=in_progress_id,
            in_progress_msg=in_progress_msg,
        )

    return {"imported": imported, "errors": errors}
