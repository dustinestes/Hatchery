# ADR-0019: Library disable / excise (soft vs teardown depth)

- **Status:** Accepted
- **Date:** 2026-09-26
- **Issues:** Planning [#379](https://github.com/dustinestes/Hatchery/issues/379); remove classic git [#406](https://github.com/dustinestes/Hatchery/issues/406); modal [#407](https://github.com/dustinestes/Hatchery/issues/407); soft-disable chrome [#408](https://github.com/dustinestes/Hatchery/issues/408)
- **Related:** [ADR-0016](0016-library-operator-plane.md) (plane + no dual inventory root), [ADR-0017](0017-library-connections-bindings-tables.md), [ADR-0012](0012-library-cache-provenance-drift.md) / [ADR-0018](0018-library-drift-scenario-matrix.md) (linked / sync), [ADR-0020](0020-library-forge-path-only.md) (classic git removed)
- **How-to:** [library.md - Enable / disable Library](../library.md#enable--disable-library-379)

## Context

Turning Library off today only flips `library_enabled` (and resolves Library Alerts). Operators who hydrated a Controller from Library and want a quiet standalone data dir need a clear contract for **soft offline** vs **teardown depth**, without a second inventory tree under `data-dir/library/{domain}/`.

Surgical per-connection / per-binding remove modals already exist; they do not scale when many connections must go with a full disable.

## Decision

### Vocabulary

| Term | Role |
|---|---|
| **Enabled** / **Disabled** | Durable `library_enabled` flag |
| **Clear** (Connections / Content / Links) | Teardown depth on the Enabled → Disabled transition - not a parked Library state |

UI copy uses **linked** / **Clear Links**, not internal “provenance.” Implementation may still say provenance in code and ADRs.

### Soft disable

When Library is turned **off** with Clear Connections **off** and Linked Cached files = **Leave as-is**:

- Library nav / Connections / From library… hidden
- Library validators no-op; Library-scoped Alerts resolved (as today)
- Domain Cached inventory stays hatchable (no Clutch invalidation cascade)
- Link rows **kept** so re-enable can restore linked UX
- Sync / re-attach chrome suppressed while disabled; small “was linked from Library” cue ([#408](https://github.com/dustinestes/Hatchery/issues/408))

Soft disable removes the **source-link mechanism from the UI**, not the files or hatchability.

### Disable / excise modal

On Settings → General, when turning **Enable Library** from on to off, show a modal (same toggle grammar as connection remove) before committing. Cancel leaves Library **Enabled**.

| Control | Default | Effect |
|---|---|---|
| **Clear Connections** (checkbox) | off | Delete all connections, kinds, and bindings. Does not delete domain cache files by itself |
| **Linked Cached files** (radio) | **Leave as-is** | Soft: keep link rows for re-enable |
| | **Clear Content** | Delete Library-linked operator-cache files and their link rows. Never deletes unlinked local-only files |
| | **Clear Links** | Drop link rows / linked indicators; **keep** the files |

Clear Connections is independent of the linked-files radio. UI: one help tip on the radio **group**, not per option.

**Single registry clear:** do **not** offer bindings-only or connections-without-bindings on this modal. That half-state has no operator value on a full Library disable. Surgical remove while Library stays Enabled remains on Connections.

### Disk layout

- Operator bytes stay in `automation/scripts/`, `clutches/`, `media/…` - **no** dual attributed root under `data-dir/library/{domain}/` ([ADR-0016](0016-library-operator-plane.md))
- Classic `{data_dir}/library/git/` clone cache is removed ([ADR-0020](0020-library-forge-path-only.md) / [#406](https://github.com/dustinestes/Hatchery/issues/406)). Clear Connections need not delete clone dirs; connection delete still GCs any leftover dir under that path

### Non-goals

- Cascading Clutch invalidation / alerts when Library is disabled or content cleared
- Full Cleaners ([#361](https://github.com/dustinestes/Hatchery/issues/361))
- Rich “WHERE” history UI beyond the small linked cue
- Settings YAML import running excise (import keeps flag + registry as today)

## Consequences

**Good**

- One clear story for temporary offline vs teardown
- Operator language matches linked / Content vocabulary
- Aligns with ADR-0016 (no second inventory root)

**Neutral / follow-on**

- Implementation: [#407](https://github.com/dustinestes/Hatchery/issues/407) (modal), [#408](https://github.com/dustinestes/Hatchery/issues/408) (soft-disable chrome)
- Pre-work: [#406](https://github.com/dustinestes/Hatchery/issues/406) remove classic git ([ADR-0020](0020-library-forge-path-only.md))

**Bad / accepted cost**

- Off-transition requires a confirm modal (extra click when tearsdown are unused)

## Alternatives

| Alternative | Why not |
|---|---|
| Dual `data-dir/library/{domain}` inventory | Dual roots across list/import/hatch/Nest/drift |
| Separate Clear Connections vs Clear Bindings on this modal | Half-removal; bindings without connections (or the reverse) is useless on full disable |
| Allow Clear Content and Clear Links both on | Conflicting outcomes; use a radio (Leave / Content / Links) instead |
| Two checkboxes with JS mutex for Content vs Links | Checkboxes imply independent opts; radio group matches exclusive choice |
| Fold Clear Links into Clear Content | Different operator intents (delete vs keep-as-local) |
| Keep Sync while Disabled | Source mechanism is off; Sync would fail or confuse |
