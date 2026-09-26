# ADR-0019: Library disable / excise (soft vs teardown depth)

- **Status:** Accepted
- **Date:** 2026-09-26
- **Issues:** Planning [#379](https://github.com/dustinestes/Hatchery/issues/379); remove classic git [#406](https://github.com/dustinestes/Hatchery/issues/406); modal [#407](https://github.com/dustinestes/Hatchery/issues/407); soft-disable chrome [#408](https://github.com/dustinestes/Hatchery/issues/408)
- **Related:** [ADR-0016](0016-library-operator-plane.md) (plane + no dual inventory root), [ADR-0017](0017-library-connections-bindings-tables.md), [ADR-0012](0012-library-cache-provenance-drift.md) / [ADR-0018](0018-library-drift-scenario-matrix.md) (linked / sync), [ADR-0009](0009-library-git-checkout-cache.md) (clone cache until [#406](https://github.com/dustinestes/Hatchery/issues/406))
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

When Library is turned **off** and all teardown toggles are **off**:

- Library nav / Connections / From library… hidden
- Library validators no-op; Library-scoped Alerts resolved (as today)
- Domain Cached inventory stays hatchable (no Clutch invalidation cascade)
- Link rows **kept** so re-enable can restore linked UX
- Sync / re-attach chrome suppressed while disabled; small “was linked from Library” cue ([#408](https://github.com/dustinestes/Hatchery/issues/408))

Soft disable removes the **source-link mechanism from the UI**, not the files or hatchability.

### Disable / excise modal

On Settings → General, when turning **Enable Library** from on to off, show a modal (same toggle grammar as connection remove) before committing. Defaults all **off**. Cancel leaves Library **Enabled**.

| Toggle (UI) | Helper | Effect |
|---|---|---|
| **Clear Connections** | Includes all bindings | Delete all connections, kinds, and bindings. Does not delete domain cache files by itself |
| **Clear Content** | Deletes Cached files that came from Library | Delete Library-linked operator-cache files and their link rows. Never deletes unlinked local-only files |
| **Clear Links** | Leaves files as local inventory (no Library link) | Drop link rows / linked indicators; **keep** the files |

**Clear Content** and **Clear Links** are **mutually exclusive** (UI mutex): one deletes bytes, the other keeps them. Clear Connections is independent of that pair.

**Single registry clear:** do **not** offer bindings-only or connections-without-bindings on this modal. That half-state has no operator value on a full Library disable. Surgical remove while Library stays Enabled remains on Connections.

### Disk layout

- Operator bytes stay in `automation/scripts/`, `clutches/`, `media/…` - **no** dual attributed root under `data-dir/library/{domain}/` ([ADR-0016](0016-library-operator-plane.md))
- `{data_dir}/library/git/` is only the classic **`type: git`** shallow-clone cache ([ADR-0009](0009-library-git-checkout-cache.md)). Forge never writes there. Prefer removing `type: git` ([#406](https://github.com/dustinestes/Hatchery/issues/406)) **before** modal implementation so Clear Connections need not delete clones. Until then, Clear Connections also removes those clone dirs for any remaining git connections

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
- Pre-work: [#406](https://github.com/dustinestes/Hatchery/issues/406) remove classic git

**Bad / accepted cost**

- Off-transition requires a confirm modal (extra click when tearsdown are unused)

## Alternatives

| Alternative | Why not |
|---|---|
| Dual `data-dir/library/{domain}` inventory | Dual roots across list/import/hatch/Nest/drift |
| Separate Clear Connections vs Clear Bindings on this modal | Half-removal; bindings without connections (or the reverse) is useless on full disable |
| Allow Clear Content and Clear Links both on | Conflicting outcomes for the same linked set |
| Fold Clear Links into Clear Content | Different operator intents (delete vs keep-as-local) |
| Keep Sync while Disabled | Source mechanism is off; Sync would fail or confuse |
