# ADR-0036: Pre-mint VM UUID and nest_storage/{vm_id} colocation

- **Status:** Accepted
- **Date:** 2026-10-17
- **Issues:** [#587](https://github.com/dustinestes/Hatchery/issues/587)
- **Related:** [ADR-0035](0035-nest-install-media-lifecycle.md), [#144](https://github.com/dustinestes/Hatchery/issues/144), [#538](https://github.com/dustinestes/Hatchery/issues/538), [#215](https://github.com/dustinestes/Hatchery/issues/215)

## Context

ADR-0035 placed durable answer media under `{nest_cache}/nest-work/answer-media/` keyed by VM display name. That conflates Nest **content** cache with per-VM hypervisor files, breaks on rename / batch name suffixes, and leaves disks elsewhere (pool or Clutch `storage_path/{name}.qcow2`).

Answer media must exist before domain create completes attach, so identity cannot be read back from the hypervisor first.

## Decision

1. **Pre-mint `vm_id`:** Hatch mints a UUID before `create_vm`, persists it on `hatch_vm_status`, and passes it into the provider.
2. **Colocate Nest VM files:**
   ```text
   {nest_storage}/{vm_id}/
     disk.qcow2|vhdx
     autounattend.img|iso   # ephemeral; delete after install media cleanup
   ```
3. **Path resolve:** Nest `nest_storage` (Nest detail volumes / `extra.nest_storage`; [ADR-0039](0039-nest-health-gate-and-nest-storage.md) / #538) → provider default (libvirt pool path when present; Hyper-V VirtualHardDiskPath when queryable). Clutch `storage_path` removed ([#600](https://github.com/dustinestes/Hatchery/issues/600)); legacy YAML keys are ignored on load with a WARN. Never write new answer media under Controller `data_dir` / `nest_cache`.
4. **Hypervisor identity:** Libvirt `virt-install --uuid`. Hyper-V has no create-time Id API; Nest storage `vm_id` is the directory name and is recovered from the disk path parent for `get_vm_uuid` / `get_vm_name_by_uuid`.
5. **Cleanup:** After answer detach+delete, `rmdir` the VM dir if empty. Destroy removes leftovers and empty dirs. Legacy `nest-work` files may be deleted on destroy when found by name. Libvirt Destroy ejects clutch-snapshot (or catalog-root) install media before `--remove-all-storage` so shared OS/VirtIO ISOs are not deleted ([#601](https://github.com/dustinestes/Hatchery/issues/601)).

## Consequences

- `nest_cache` stays content-only (#215).
- Batch hatch name suffixes (#588) can rename guests without moving Nest files.
- Operators need Nest `nest_storage` (or a usable provider default) when hatching; Clutches stay Nest-agnostic (#600).
- ADR-0035 path decision for answer media is superseded for layout; cleanup section timing/WARN policy remains.

## Alternatives considered

- **Keep name-keyed nest-work under nest_cache:** Rejected - wrong plane; rename/batch fragile.
- **Mint UUID only after create:** Rejected - answer media must be packed before attach.
- **Force Hyper-V Id to match pre-mint:** Rejected - New-VM does not accept a caller Id.
