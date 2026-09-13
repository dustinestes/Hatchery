"""Nest cache ensure and hatch preflight (basename + SHA-256).

For a local Nest, the operator ``data_dir`` is the Nest cache — preflight is a
filesystem check (no copy). Remote Nest copy/verify over Nest transport lands
with #207 / #215; this module refuses remote ensure until that exists so hatch
never attaches operator-only paths over the WAN.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lib import config as config_lib
from lib.clutch import Clutch, VMConfig
from lib.library import sha256_file
from lib.nest_transport import NestConnectionConfig

ArtifactKind = Literal[
    "media/iso",
    "media/virtio",
    "automation/os_config",
    "automation/scripts",
]

_KIND_DIR: dict[ArtifactKind, str] = {
    "media/iso": "media/iso",
    "media/virtio": "media/virtio",
    "automation/os_config": "automation/os_config",
    "automation/scripts": "automation/scripts",
}

ARTIFACT_KINDS = frozenset(_KIND_DIR)


class NestCacheError(RuntimeError):
    """Raised when Nest cache ensure/preflight cannot proceed."""


@dataclass(frozen=True)
class CacheArtifact:
    """One Nest-cache-backed file required for hatch or ensure."""

    kind: ArtifactKind
    basename: str
    sha256: str | None = None
    vm_name: str | None = None
    # Absolute path from the Clutch when the operator used a full path.
    absolute_path: str | None = None

    @property
    def relative_path(self) -> str:
        return f"{_KIND_DIR[self.kind]}/{self.basename}"


@dataclass(frozen=True)
class ArtifactIssue:
    artifact: CacheArtifact
    reason: Literal["missing", "checksum_mismatch", "absolute_path_remote", "not_a_file"]
    detail: str = ""


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    issues: list[ArtifactIssue]

    def error_message(self) -> str:
        if self.ok:
            return ""
        lines: list[str] = []
        for issue in self.issues:
            art = issue.artifact
            label = art.relative_path
            if art.vm_name:
                label = f"{label} (VM {art.vm_name})"
            if issue.reason == "missing":
                lines.append(f"Nest cache missing: {label}")
            elif issue.reason == "checksum_mismatch":
                lines.append(f"Nest cache checksum mismatch: {label}{issue.detail}")
            elif issue.reason == "absolute_path_remote":
                lines.append(f"Nest cache refuses operator absolute path on remote Nest: {label}")
            elif issue.reason == "not_a_file":
                lines.append(f"Nest cache path is not a file: {label}")
            else:
                lines.append(f"Nest cache issue ({issue.reason}): {label}")
        return "; ".join(lines)


def _safe_basename(name: str) -> str:
    return Path(name).name


def _artifact_from_name(
    kind: ArtifactKind,
    raw: str,
    *,
    vm_name: str | None = None,
    sha256: str | None = None,
) -> CacheArtifact:
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"{kind} name is required")
    path = Path(text)
    if path.is_absolute():
        return CacheArtifact(
            kind=kind,
            basename=_safe_basename(text),
            sha256=sha256,
            vm_name=vm_name,
            absolute_path=str(path),
        )
    return CacheArtifact(
        kind=kind,
        basename=_safe_basename(text),
        sha256=sha256,
        vm_name=vm_name,
    )


def collect_vm_artifacts(vm: VMConfig) -> list[CacheArtifact]:
    """Collect Nest-cache artifacts required to hatch one VM."""
    arts: list[CacheArtifact] = [
        _artifact_from_name("media/iso", vm.os_media, vm_name=vm.name),
    ]
    if vm.virtio_drivers:
        arts.append(_artifact_from_name("media/virtio", vm.virtio_drivers, vm_name=vm.name))
    if vm.os_config:
        arts.append(_artifact_from_name("automation/os_config", vm.os_config, vm_name=vm.name))
    for script in vm.automations:
        arts.append(_artifact_from_name("automation/scripts", script.name, vm_name=vm.name))
    return arts


def collect_clutch_artifacts(clutch: Clutch) -> list[CacheArtifact]:
    """Dedupe Nest-cache artifacts for all VMs in a Clutch (first SHA wins)."""
    by_key: dict[tuple[str, str], CacheArtifact] = {}
    for vm in clutch.vms:
        for art in collect_vm_artifacts(vm):
            key = (art.kind, art.basename if not art.absolute_path else art.absolute_path)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = art
            elif existing.sha256 is None and art.sha256:
                by_key[key] = art
    return list(by_key.values())


def resolve_nest_path(artifact: CacheArtifact, nest_root: Path) -> Path:
    """Resolve where an artifact must exist in the Nest cache tree."""
    if artifact.absolute_path:
        return Path(artifact.absolute_path)
    return nest_root / _KIND_DIR[artifact.kind] / artifact.basename


def verify_local(
    artifacts: list[CacheArtifact],
    nest_root: Path | None = None,
) -> PreflightResult:
    """Filesystem check under the Nest cache root (operator data_dir for local Nest)."""
    root = Path(nest_root) if nest_root is not None else config_lib.data_dir()
    issues: list[ArtifactIssue] = []
    for art in artifacts:
        path = resolve_nest_path(art, root)
        if not path.exists():
            issues.append(ArtifactIssue(art, "missing"))
            continue
        if not path.is_file():
            issues.append(ArtifactIssue(art, "not_a_file"))
            continue
        if art.sha256:
            actual = sha256_file(path)
            if actual.lower() != art.sha256.lower():
                issues.append(
                    ArtifactIssue(
                        art,
                        "checksum_mismatch",
                        detail=f" (expected {art.sha256[:12]}…, got {actual[:12]}…)",
                    )
                )
    return PreflightResult(ok=not issues, issues=issues)


def preflight(
    artifacts: list[CacheArtifact],
    *,
    nest: NestConnectionConfig | None = None,
    nest_root: Path | None = None,
) -> PreflightResult:
    """Verify required artifacts exist on the Nest cache before create/attach."""
    conn = nest or NestConnectionConfig(location="local")
    if conn.location == "remote":
        remote_issues: list[ArtifactIssue] = []
        for art in artifacts:
            if art.absolute_path:
                remote_issues.append(
                    ArtifactIssue(
                        art,
                        "absolute_path_remote",
                        detail="copy into Nest cache instead of attaching operator paths",
                    )
                )
        if remote_issues:
            return PreflightResult(ok=False, issues=remote_issues)
        # No Nest file transport yet (#207 / #215) — fail closed.
        raise NestCacheError(
            "Remote Nest cache ensure is not available yet "
            "(Nest registry / transport copy — see #207 / #215). "
            "Hatch requires content in the Nest cache; operator-only paths are not attached over WAN."
        )
    return verify_local(artifacts, nest_root=nest_root)


def ensure(
    artifacts: list[CacheArtifact],
    *,
    nest: NestConnectionConfig | None = None,
    nest_root: Path | None = None,
    operator_root: Path | None = None,
) -> PreflightResult:
    """Ensure Nest cache has the artifacts (local: verify; remote: copy — stubbed).

    Local Nest: operator cache is Nest cache — no network copy.
    Remote Nest: raises until transport copy lands (#215).
    """
    conn = nest or NestConnectionConfig(location="local")
    if conn.location == "remote":
        # Future: copy from operator_root → nest via Nest transport, verify SHA-256.
        _ = operator_root  # reserved for remote copy source
        raise NestCacheError(
            "Remote Nest cache ensure is not available yet "
            "(Nest registry / transport copy — see #207 / #215)."
        )
    return verify_local(artifacts, nest_root=nest_root)


def preflight_clutch(
    clutch: Clutch,
    *,
    nest: NestConnectionConfig | None = None,
    nest_root: Path | None = None,
    run_ensure: bool = False,
) -> PreflightResult:
    """Collect clutch artifacts and preflight (optionally via ensure)."""
    artifacts = collect_clutch_artifacts(clutch)
    if run_ensure:
        return ensure(artifacts, nest=nest, nest_root=nest_root)
    return preflight(artifacts, nest=nest, nest_root=nest_root)
