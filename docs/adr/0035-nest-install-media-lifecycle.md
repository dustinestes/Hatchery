# ADR-0035: Nest install media lifecycle (durable hatch-work + post-ready cleanup)

- **Status:** Accepted (answer media **path** layout superseded by [ADR-0036](0036-pre-mint-vm-uuid-nest-storage.md) / [#587](https://github.com/dustinestes/Hatchery/issues/587); cleanup section timing and WARN-continue remain)
- **Date:** 2026-10-17
- **Issues:** [#144](https://github.com/dustinestes/Hatchery/issues/144)
- **Related:** [ADR-0007](0007-library-nest-content-planes.md), [ADR-0024](0024-answer-files-product-model.md), [ADR-0032](0032-guest-environment-ensure-job.md), [ADR-0036](0036-pre-mint-vm-uuid-nest-storage.md), [#215](https://github.com/dustinestes/Hatchery/issues/215), [#587](https://github.com/dustinestes/Hatchery/issues/587)

## Context

Hatch attaches OS install ISO, optional VirtIO CD, and silent answer media (libvirt floppy / Hyper-V DVD ISO) for Windows unattended install. Answer media was written under system temp and left attached until Destroy. Temp reapers and moved/deleted ISOs then broke later VM starts. Detach belongs on the Nest plane after first-boot; it must not be folded into guest environment ensure (ADR-0032).

## Decision

1. **Durable answer media path:** Originally
   `{nest_cache}/nest-work/answer-media/{vm_name}-autounattend.{img|iso}` (#144).
   **Successor layout ([ADR-0036](0036-pre-mint-vm-uuid-nest-storage.md)):** 
   `{nest_storage}/{vm_id}/autounattend.{img|iso}` colocated with `disk.qcow2|vhdx`.
   Do not use system temp. Do not store answer media under `nest_cache`.
   Ownership-prefixed ids: **`nest_cache`** (content root) vs **`nest_storage`** (per-VM Nest files).

2. **Cleanup section:** After `hatchery-ready` and guest SSH authorize succeed, and **before**
   Ending Windows setup → guest environment / fledged, run a Nest-plane section
   **install media cleanup** with pure hatchery-context bookends. Runs for automations
   and no-automations paths alike.

3. **Detach set:** OS install ISO, answer media, install-time VirtIO CD. Operator
   keep-attached additional ISOs (#122) are out of scope until keep-flags exist.

4. **Delete:** Remove Nest answer media file only after that device detached successfully
   (or when the file is already orphaned from the domain).

5. **Failure:** Cleanup is Nest hygiene, not a hatch gate. Step failures emit `WARN`
   events; hatch continues to guest environment / automations / fledged. Do not mark
   the VM `failed` because unused media could not be ejected.

6. **API:** `BaseProvider.cleanup_install_media(name) -> list[MediaCleanupStep]`.
   Default no-op. Libvirt and Hyper-V local implement; UTM/remote follow when attach exists.

7. **Destroy vs catalog ISOs ([#601](https://github.com/dustinestes/Hatchery/issues/601)):** Libvirt
   `undefine --remove-all-storage` deletes still-attached file-backed CDROM sources.
   Before undefine, eject media whose basenames match the hatch clutch snapshot
   (`os_media` / `virtio_drivers`) plus Nest answer media. With no snapshot, eject
   sources under catalog `iso_dir` / `virtio_dir`. Keep `--remove-all-storage` for
   Nest disks and any other attached volumes. Hyper-V Destroy remains VHDX-only.

## Consequences

- Fledged VMs no longer depend on install ISO / answer media paths for start.
- Answer media survives Controller reboots and temp cleaners during Windows setup.
- Event catalog gains an install media cleanup section ([events.md](../events.md)).
- Guest environment ensure remains guest-plane only (ADR-0032).

## Alternatives considered

- **Fail hatch on cleanup error:** Rejected - media is unused after first-boot; abandoning
  setup is worse than leaving a WARN and a stuck tray.
- **Cleanup inside guest environment:** Rejected - Nest hypervisor ops are not guest env.
- **Controller `data_dir` only for Remote Nest answer files:** Rejected - hypervisor opens
  Nest paths; remote attach needs Nest-side cache (#215).
