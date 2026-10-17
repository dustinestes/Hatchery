# ADR-0035: Nest install media lifecycle (durable hatch-work + post-ready cleanup)

- **Status:** Accepted
- **Date:** 2026-10-17
- **Issues:** [#144](https://github.com/dustinestes/Hatchery/issues/144)
- **Related:** [ADR-0007](0007-library-nest-content-planes.md), [ADR-0024](0024-answer-files-product-model.md), [ADR-0032](0032-guest-environment-ensure-job.md), [#215](https://github.com/dustinestes/Hatchery/issues/215)

## Context

Hatch attaches OS install ISO, optional VirtIO CD, and silent answer media (libvirt floppy / Hyper-V DVD ISO) for Windows unattended install. Answer media was written under system temp and left attached until Destroy. Temp reapers and moved/deleted ISOs then broke later VM starts. Detach belongs on the Nest plane after first-boot; it must not be folded into guest environment ensure (ADR-0032).

## Decision

1. **Durable answer media path:** Rendered answer media lives under Nest cache
   `{nest_cache}/nest-work/answer-media/{vm_name}-autounattend.{img|iso}`.
   For a local Nest, operator `data_dir` is Nest cache (ADR-0007). Do not use system temp.
   Remote Nest uses the same relative path on the Nest cache once ensure/copy (#215) lands.
   Ownership-prefixed ids: Nest registry / provider field **`nest_cache`** (content root).
   Guest disk roots are **`nest_storage`** ([#538](https://github.com/dustinestes/Hatchery/issues/538));
   do not reuse bare `storage_path` / `cache_root` for Nest-owned paths.

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
