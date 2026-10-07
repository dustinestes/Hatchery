# ADR-0033: Online / command-only Software packages

- **Status:** Accepted
- **Date:** 2026-10-07
- **Issues:** [#561](https://github.com/dustinestes/Hatchery/issues/561); Software model [ADR-0025](0025-software-product-model.md); offline staging [#475](https://github.com/dustinestes/Hatchery/issues/475); forge release-asset transform (separate) [#517](https://github.com/dustinestes/Hatchery/issues/517)

## Context

ADR-0025 already treats `{os}/{arch}/` offline payload trees as **optional**. Hatch stages nothing when that dir is missing and still runs the resolved unit's `install` / `uninstall` / `detect` commands ([`lib/software_provision.py`](../../lib/software_provision.py) command-only path).

Operators and Hatchery-Library need first-class samples that install **without** shipping binaries in git: the guest fetches an installer over HTTPS or invokes a guest package manager (for example winget). That is a different acquisition story from Controller-side Library materialize or forge release-asset transforms (#517).

## Decision

1. **Online / command-only is a first-class Software content shape.** A package may be only `software.yaml` under `software/{Publisher.Product.Version}/` with no `{os}/{arch}/` payload tree. Schema and hatch path stay the same as offline packages.
2. **Cross-platform units remain required.** YAML-only does not flatten to a single global command. Authors still declare `platforms.{os}.{arch}` with per-unit lifecycle commands. Hatch selects the guest OS + arch unit as today. Multi-OS online packages may mix winget / apt / brew units with zero payload files.
3. **No `source:` schema in v1.** Download URLs, winget package ids, and silent switches live in authored `install.command` (and matching uninstall/detect). Do not add Controller URL materialize into `automation/software/`.
4. **Guest outbound network and tool presence are operator concerns.** HTTPS downloads need guest internet. Winget needs App Installer (or an opt-in Software package that bootstraps it). Hatchery does **not** bake winget into `hatchery-setup-windows.ps1`; Clutch Software order is how operators opt in.
5. **Library docs stay light.** Hatchery-Library ships living yaml examples plus a short README shapes sketch. Full operator how-to lives in Hatchery [`docs/software.md`](../software.md).
6. **#517 stays separate.** Forge GitHub release assets → Software transform is Controller Library acquisition, not guest-side install commands.

## Consequences

- Hatchery-Library can ship hypervisor guest tools (SPICE, QEMU Guest Agent, VirtIO guest tools via winget) and an opt-in Desktop App Installer bootstrap without committing large binaries. VirtIO via Software is a post-install alternative to attaching the virtio-win ISO; Setup-time storage drivers may still need media.
- Offline MSI samples and online packages share one schema and one hatch walk; only staging differs.
- Operators who need winget before a winget-based Software row put the bootstrap package earlier in Clutch `automations` (no dependency solver).
- Silent install caveats (UAC, Local System for some driver installers) remain the same as offline Software; authors document them in commands / Library comments, not a second product path.

## Alternatives

| Option | Why not |
|---|---|
| Controller downloads URL into cache on pull | Second acquisition plane; overlaps #517; not needed when guest can fetch |
| New `source:` / `download_url` schema keys | Premature; commands already express HTTPS and winget |
| Bake winget into first-boot setup | Removes opt-in; changes every Windows guest |
| Guest-only string packages without `platforms` | Breaks cross-OS SoR locked in ADR-0025 |

## Related docs

- Operator how-to: [`docs/software.md`](../software.md) (offline vs online / command-only)
- Product model: [ADR-0025](0025-software-product-model.md)
