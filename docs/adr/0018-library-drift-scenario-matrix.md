# ADR-0018: Library drift scenario matrix + `source_missing`

- **Status:** Accepted
- **Date:** 2026-09-25
- **Issues:** Planning parent [#370](https://github.com/dustinestes/Hatchery/issues/370); evaluate [#382](https://github.com/dustinestes/Hatchery/issues/382); Cached UX [#383](https://github.com/dustinestes/Hatchery/issues/383); Content pane [#384](https://github.com/dustinestes/Hatchery/issues/384)
- **Extends:** [ADR-0012](0012-library-cache-provenance-drift.md) (provenance + bidirectional evaluate remain; tip-missing vocabulary is refined here)
- **Related:** [ADR-0016](0016-library-operator-plane.md) (Library → Content north star), [#364](https://github.com/dustinestes/Hatchery/issues/364) (re-attach basename lock), [#361](https://github.com/dustinestes/Hatchery/issues/361) (Cleaners / ghost provenance), [#379](https://github.com/dustinestes/Hatchery/issues/379) (Library soft disable)
- **How-to:** [library.md - Drift scenario matrix](../library.md#drift-scenario-matrix-370)

## Context

ADR-0012 locked four `drift_state` values: `in_sync`, `out_of_sync`, `unknown`, `orphan`. Tip resolution that returns no digest while the Cached file still exists (remote rename, remote delete, wrong `relative_path`) lands in **`unknown`** today - the same bucket as rate limits, disabled connections, and tip kinds that cannot be confirmed cheaply (HTTPS without checksum, API without metadata SHA).

Operators reasonably treat “source path gone” as an actionable problem (re-attach, Sync, or remove attribution), not “Tip unknown.” Planning issue [#370](https://github.com/dustinestes/Hatchery/issues/370) needs an explicit matrix and a fifth state so implementation and UX do not invent buckets ad hoc.

## Decision

1. **Keep ADR-0012 mechanics** (SQLite provenance, bidirectional digests, Sync = pull then evaluate, never download solely to compare, orphan on missing connection/binding ids, validator Alert rules for `out_of_sync`).

2. **Add `drift_state` value `source_missing`.** Meaning: connection and binding ids are still valid, tip resolution ran without a transient failure, and the recorded tip path / identity cannot be resolved (path deleted, renamed away, or otherwise absent from a successful tip index / single-path resolve), while the Cached file may still exist.

3. **Keep `unknown` for tip unavailable** - transient or non-actionable tip confirmation failure only:
   - Connection disabled
   - Tip index / resolve rate-limited or transport failed in a way that does not prove path absence (403/429, network error)
   - Tip kind cannot be confirmed cheaply (HTTPS without checksum header; API without metadata SHA) even though the object may still exist

4. **Do not collapse `source_missing` into `orphan`.** Orphan = registry soft-ref missing (connection/binding id gone). Source missing = refs valid, tip path gone. Recovery UX differs (orphan always re-attach ids; source missing often re-attach `relative_path` or remove).

5. **Do not treat `source_missing` as `out_of_sync`.** Sync is still a correction action (see below), but path-gone must not inflate domain drift Alert counts or auto-sync loops that cannot succeed until the path is fixed.

6. **Operator correction set for `source_missing`** (implementation follow-on; product lock here):

| Action | Role |
|---|---|
| **Re-attach** | Primary when the source moved (new `relative_path` and/or connection/binding). Same-basename lock ([#364](https://github.com/dustinestes/Hatchery/issues/364)) still applies; rename of basename → re-import |
| **Sync** | Attempt pull from the current provenance path after evaluate. Succeeds if the tip was restored at the same path; otherwise fails with clear copy pointing at Re-attach or Remove - do not silently no-op |
| **Remove** | Drop Library attribution for that Cached basename (delete provenance row). Optional confirm to also cull the Cached file. Distinct from Library soft-disable ([#379](https://github.com/dustinestes/Hatchery/issues/379)) |

7. **Scenario matrix (locked desired states)** - local Cached file × remote tip. UI copy may say “synced” / “out of sync”; storage remains `in_sync` / `out_of_sync`.

| Scenario | Local cache | Remote tip | Desired `drift_state` | Primary operator action |
|---|---|---|---|---|
| Unchanged | Exists, matches anchors | Tip resolves, matches anchors | `in_sync` | None (healthy link) |
| Content changed (local) | Bytes ≠ `cache_sha256_synced` | Tip unchanged | `out_of_sync` | Sync (overwrites local) |
| Content changed (remote) | Unchanged vs cache anchor | Tip digest moved (same path) | `out_of_sync` | Sync (pulls tip) |
| Both changed | Bytes drifted | Tip moved | `out_of_sync` | Sync (source wins; confirm in UX if destructive) |
| Renamed (remote) | Old basename still cached | Old `relative_path` missing; new name elsewhere | `source_missing` | Re-attach (same basename) or re-import; or Remove |
| Renamed (local) | Operator renamed/moved cache file | Provenance path / row mismatch | Ghost / Cleaner ([#361](https://github.com/dustinestes/Hatchery/issues/361)); not `source_missing` | Cleaner or re-attach after restore |
| Missing (remote) | Cache present | Tip path deleted (not renamed) | `source_missing` | Re-attach if replaced; else Remove |
| Missing (local) | Cache file gone | Tip may still exist | `out_of_sync` (cache drifted / missing) or Cleaner ghost row | Sync (restore from tip) or Cleaner |
| Connection/binding removed | Cache present | Ids gone | `orphan` | Re-attach |
| Tip unavailable | Cache present | Cannot confirm tip (rate limit, disabled, no digest kind) | `unknown` | Wait / fix connection; not Sync-as-fix |
| Basename mismatch on re-attach | - | - | API reject ([#364](https://github.com/dustinestes/Hatchery/issues/364)) | Re-import under new name |

8. **Alerts / auto-sync:** domain drift Alerts and auto-sync continue to count / walk **`out_of_sync` only**. `source_missing` and `unknown` are visible in inventory chrome and filters; they do not open the “N out of sync” Alert. Follow-on UX may add a separate Alert or badge for `source_missing` counts - not required by this ADR.

9. **Planning vs implementation.** [#370](https://github.com/dustinestes/Hatchery/issues/370) is the **planning parent** (this ADR + operator how-to matrix). Evaluate ([#382](https://github.com/dustinestes/Hatchery/issues/382)), Cached UX ([#383](https://github.com/dustinestes/Hatchery/issues/383)), and Library → Content ([#384](https://github.com/dustinestes/Hatchery/issues/384)) ship as child issues; do not implement `source_missing` in the planning PR beyond docs/ADR.

10. **Library → Content** ([#384](https://github.com/dustinestes/Hatchery/issues/384)) remains the north star home for linked/synced lifecycle chrome ([ADR-0016](0016-library-operator-plane.md)); domain Cached panes may get interim cues ([#383](https://github.com/dustinestes/Hatchery/issues/383)), but permanent lifecycle UX prefers Content.

## Consequences

**Good**

- Path-gone is actionable and distinct from rate-limit noise
- Orphan vs source missing stay separable for UX and tests
- ADR-0012 Sync/Alert semantics for true content drift stay intact

**Neutral / follow-on**

- Evaluate must distinguish “tip index succeeded, path absent” from “tip index failed” (implementation child)
- Remote rename vs delete remain indistinguishable at tip-resolve time; both are `source_missing`
- Local rename / ghost rows stay on [#361](https://github.com/dustinestes/Hatchery/issues/361)
- Content pane and Cached link/warn chrome are separate child issues: [#384](https://github.com/dustinestes/Hatchery/issues/384), [#383](https://github.com/dustinestes/Hatchery/issues/383) under [#370](https://github.com/dustinestes/Hatchery/issues/370)

**Bad / accepted cost**

- Fifth DB/UI state expands filters, badges, and tests
- Sync on `source_missing` will often fail until Re-attach; copy must explain why

## Alternatives considered

| Option | Why not |
|---|---|
| Keep path-gone as `unknown` with distinct copy only | Operators still lack a first-class correction state; filters/Alerts stay muddy |
| Fold path-gone into `out_of_sync` | Inflates Alerts and auto-sync for paths that cannot pull |
| Fold path-gone into `orphan` | Mis-labels valid connection/binding ids; wrong recovery story |
| New state without Sync | Rejected - operators asked for Re-attach, Sync, and Remove as the correction set |
