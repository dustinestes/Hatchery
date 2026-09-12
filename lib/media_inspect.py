"""Inspect media files under the Hatchery data directory (ISO / VirtIO).

Image metadata is read with the portable ``pycdlib`` library (Linux/macOS/Windows)
— no host ISO CLI tools are required for the Media panes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from lib import clutch as clutch_lib
from lib import config

# El Torito platform_id → display label
_EL_TORITO_PLATFORMS = {
    0x00: "BIOS",
    0x01: "PowerPC",
    0x02: "Mac",
    0xEF: "UEFI",
}


def resolve_media_path(subdir: str, name: str) -> Path | None:
    """Return a path under data_dir/subdir, or None if the name is invalid."""
    safe = Path(name).name
    if not safe or safe in (".", ".."):
        return None
    root = (config.data_dir() / "media" / subdir).resolve()
    candidate = (root / safe).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def scan_media_dir(subdir: str) -> list[dict]:
    """Return inventory metadata for files in media/<subdir>/."""
    rel_root = f"media/{subdir}"
    path = config.data_dir() / rel_root
    if not path.exists():
        return []
    items: list[dict] = []
    for f in sorted(path.iterdir()):
        if not f.is_file():
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        modified = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        items.append(
            {
                "name": f.name,
                "relative_path": f"{rel_root}/{f.name}",
                "absolute_path": str(f.resolve()),
                "size_bytes": st.st_size,
                "modified_at": modified,
            }
        )
    return items


def media_used_by(field: str) -> dict[str, list[dict]]:
    """Map media basename → [{clutch, clutch_name, vm}, ...] for os_media or virtio_drivers."""
    if field not in ("os_media", "virtio_drivers"):
        raise ValueError(f"unsupported media field: {field}")
    usage: dict[str, list[dict]] = {}
    clutches_dir = config.data_dir() / "clutches"
    if not clutches_dir.exists():
        return usage
    for path in sorted(clutches_dir.glob("*.yaml")):
        try:
            clutch = clutch_lib.load(path)
        except Exception:
            continue
        clutch_file = Path(path).name
        for vm in clutch.vms:
            value = getattr(vm, field, None)
            if not value:
                continue
            basename = Path(str(value)).name
            usage.setdefault(basename, []).append(
                {"clutch": clutch_file, "clutch_name": clutch.name, "vm": vm.name}
            )
    return usage


def _empty_probe(*, error: str | None = None) -> dict:
    return {
        "available": False,
        "volume_id": None,
        "publisher": None,
        "app_id": None,
        "created_at": None,
        "boot": None,
        "backend": None,
        "error": error,
    }


def _decode_iso_str(value) -> str | None:
    """Normalize pycdlib identifier bytes / FileOrTextIdentifier to text."""
    if value is None:
        return None
    if hasattr(value, "text"):
        value = value.text
    if isinstance(value, (bytes, bytearray)):
        text = bytes(value).decode("utf-8", errors="replace")
    else:
        text = str(value)
    text = text.replace("\x00", "").strip()
    return text or None


def _format_pvd_date(date_obj) -> str | None:
    """Format pycdlib VolumeDescriptorDate for display."""
    if date_obj is None:
        return None
    year = getattr(date_obj, "year", None)
    if not year:
        return None
    try:
        return (
            f"{int(date_obj.year):04d}-{int(date_obj.month):02d}-"
            f"{int(date_obj.dayofmonth):02d} "
            f"{int(date_obj.hour):02d}:{int(date_obj.minute):02d}:"
            f"{int(date_obj.second):02d}"
        )
    except (TypeError, ValueError, AttributeError):
        return None


def _boot_from_eltorito_catalog(catalog) -> str | None:
    """Build BIOS/UEFI label from a pycdlib EltoritoBootCatalog."""
    if catalog is None:
        return "None"
    plats: list[str] = []
    seen: set[str] = set()

    def add(platform_id) -> None:
        if platform_id is None:
            return
        try:
            pid = int(platform_id)
        except (TypeError, ValueError):
            return
        label = _EL_TORITO_PLATFORMS.get(pid, f"0x{pid:02X}")
        if label not in seen:
            seen.add(label)
            plats.append(label)

    validation = getattr(catalog, "validation_entry", None)
    if validation is not None:
        add(getattr(validation, "platform_id", None))
    # Initial entry is the default BIOS boot image when present.
    initial = getattr(catalog, "initial_entry", None)
    if initial is not None and getattr(initial, "boot_indicator", 0):
        add(0x00)
    for section in getattr(catalog, "sections", None) or []:
        add(getattr(section, "platform_id", None))
    return ", ".join(plats) if plats else "None"


def probe_iso(path: Path) -> dict:
    """Probe an ISO-like file with pycdlib. Never raises."""
    if not path.is_file():
        return _empty_probe(error="not found")
    try:
        import pycdlib

        iso = pycdlib.PyCdlib()
        iso.open(str(path))
        try:
            pvd = iso.pvd
            volume_id = _decode_iso_str(getattr(pvd, "volume_identifier", None))
            publisher = _decode_iso_str(getattr(pvd, "publisher_identifier", None))
            app_id = _decode_iso_str(getattr(pvd, "application_identifier", None))
            created_at = _format_pvd_date(getattr(pvd, "volume_creation_date", None))
            boot = _boot_from_eltorito_catalog(getattr(iso, "eltorito_boot_catalog", None))
        finally:
            iso.close()
    except Exception as exc:
        return _empty_probe(error=str(exc))

    return {
        "available": True,
        "volume_id": volume_id,
        "publisher": publisher,
        "app_id": app_id,
        "created_at": created_at,
        "boot": boot,
        "backend": "pycdlib",
        "error": None,
    }
