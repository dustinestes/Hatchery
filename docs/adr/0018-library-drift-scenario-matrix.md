# ADR-0018: Library source reachability + sync state (scenario matrix)

- **Status:** Accepted
- **Date:** 2026-09-25
- **Issues:** Planning parent [#370](https://github.com/dustinestes/Hatchery/issues/370); evaluate [#382](https://github.com/dustinestes/Hatchery/issues/382); Cached UX [#383](https://github.com/dustinestes/Hatchery/issues/383); Content pane [#384](https://github.com/dustinestes/Hatchery/issues/384)
- **Extends:** [ADR-0012](0012-library-cache-provenance-drift.md) (provenance + digests + Sync = pull-then-evaluate remain; single `drift_state` vocabulary is refined into two axes here)
- **Related:** [ADR-0016](0016-library-operator-plane.md) (Library → Content north star), [#364](https://github.com/dustinestes/Hatchery/issues/364) (re-attach basename lock), [#361](https://github.com/dustinestes/Hatchery/issues/361) (Cleaners / ghost provenance), [#379](https://github.com/dustinestes/Hatchery/issues/379) (Library soft disable)
- **How-to:** [library.md - Drift scenario matrix](../library.md#drift-scenario-matrix-370)

## Context

ADR-0012 locked one column, `drift_state` (`in_sync` | `out_of_sync` | `unknown` | `orphan`). That mixed two different questions:

1. Can we resolve the attributed **source** object?
2. If so, does the Cached file **agree** with that source?

Rate limits, network failures, disabled connections, and “no cheap digest” are **known** outcomes. Calling them `unknown` was wrong. Path-gone (remote rename/delete) is also known and actionable, not the same as a throttle.

Operators need clear correction paths (Re-attach, Sync, Remove) when the source is missing, without inflating Sync Alerts for communication failures.

## Decision

### Two axes (not more values in one enum)

1. **`source_status`** - can we reach / resolve the attributed tip? Always set for provenance rows by evaluate / validator.

| Value | Meaning |
|---|---|
| `ok` | Tip resolved (digest + kind available for compare) |
| `missing` | Tip check succeeded; path/object absent (remote rename/delete) |
| `orphan` | Connection or binding id missing from the registry |
| `disabled` | Connection `enabled: false` |
| `rate_limited` | Tip index / resolve hit 403/429 (known throttle) |
| `unreachable` | Other transport / tip-index failure (network, DNS, 5xx, etc.) |
| `unconfirmable` | Object may still exist; we will not download a body solely to compare (HTTPS without checksum; API without metadata SHA) |

2. **`sync_state`** - cache vs tip comparison. **Validator / evaluate only** (never a direct operator edit). Written in the **same** evaluate pass that already fetched tip data - do not make a second network round-trip to “sync-check.”

| Value | When |
|---|---|
| `in_sync` | `source_status == ok` and digests/anchors agree (ADR-0012 compare rules) |
| `out_of_sync` | `source_status == ok` and cache and/or tip drifted (or live identity mismatch) |
| unset / null | **`source_status != ok`** - sync was **not** evaluated (we cannot reach a comparable tip). Clear any prior sync value so the UI never shows stale “in sync” during a rate limit |

**`sync_state` is not reachability.** Reachability lives only in `source_status`. If status is anything other than `ok`, leave sync unset.

3. **`source_status_message`** - companion text column on the provenance row (set whenever `source_status` is written).

   - Prefer **known catalog messages** for common codes (stable, translatable, filter-friendly)
   - When the failure carries detail the operator should read (API body snippet, HTTP reason, exception summary), store that detail (trimmed/sanitized) so the UI can surface it without inventing a new status code per vendor string
   - `ok` may use an empty message or a short catalog line (“Source reachable”)

### Catalog (initial; implementation may extend without new ADR if codes stay the same)

| `source_status` | Known message (default) |
|---|---|
| `ok` | (empty or “Source reachable”) |
| `missing` | “Source path not found at the recorded location” |
| `orphan` | “Library connection missing” / “Library binding missing” (as today) |
| `disabled` | “Library connection is disabled” |
| `rate_limited` | “Source tip check rate-limited; try again later” |
| `unreachable` | “Could not reach Library source” + optional detail |
| `unconfirmable` | “Source tip cannot be confirmed without downloading the file” |

### Mechanics kept from ADR-0012

4. Provenance key, digest columns, Sync = pull then evaluate, never download solely to compare, forge tip batching, orphan on missing ids, optional cascade-delete on connection/binding remove - unchanged.

5. **Alerts / auto-sync:** count and walk **`sync_state == out_of_sync` only**. Non-`ok` `source_status` values are inventory/filter chrome (and may get separate badges later); they do not open the “N out of sync” Alert.

6. **Operator correction when `source_status == missing`:**

| Action | Role |
|---|---|
| **Re-attach** | Primary when the source moved. Same-basename lock ([#364](https://github.com/dustinestes/Hatchery/issues/364)); basename rename → re-import |
| **Sync** | Attempt pull from current provenance path (same tip fetch path as evaluate). Succeeds if tip restored; else fail with clear copy → Re-attach / Remove |
| **Remove** | Drop provenance (optional cull Cached file). Distinct from Library soft-disable ([#379](https://github.com/dustinestes/Hatchery/issues/379)) |

7. **Scenario matrix**

| Scenario | Local cache | Remote tip | `source_status` | `sync_state` | Primary action |
|---|---|---|---|---|---|
| Unchanged | Exists, matches anchors | Tip resolves, matches | `ok` | `in_sync` | None |
| Content changed (local) | Bytes ≠ cache anchor | Tip unchanged | `ok` | `out_of_sync` | Sync |
| Content changed (remote) | Unchanged | Tip moved (same path) | `ok` | `out_of_sync` | Sync |
| Both changed | Bytes drifted | Tip moved | `ok` | `out_of_sync` | Sync (source wins) |
| Renamed (remote) | Old basename cached | Old path absent | `missing` | unset | Re-attach / re-import / Remove |
| Renamed (local) | File moved | Provenance mismatch | (Cleaner / [#361](https://github.com/dustinestes/Hatchery/issues/361)) | - | Cleaner |
| Missing (remote) | Cache present | Path deleted | `missing` | unset | Re-attach or Remove |
| Missing (local) | Cache gone | Tip may exist | `ok` (if tip resolves) | `out_of_sync` | Sync or Cleaner |
| Connection/binding removed | Cache present | Ids gone | `orphan` | unset | Re-attach |
| Rate limited | Cache present | 403/429 | `rate_limited` | unset | Wait / token / interval |
| Network / tip-index failure | Cache present | Transport error | `unreachable` | unset | Fix connectivity |
| Connection disabled | Cache present | Skipped | `disabled` | unset | Enable connection |
| No cheap digest | Cache present | HTTPS/API without tip | `unconfirmable` | unset | Add checksum / accept limit |
| Basename mismatch on re-attach | - | - | (API reject) | - | Re-import |

8. **UI rollups** (filters/badges; not extra DB enums): e.g. **Communication** = `rate_limited` ∪ `unreachable`; **Needs attention** = `missing` ∪ `orphan` ∪ (`sync_state == out_of_sync`). Detail shows `source_status` + `source_status_message`.

9. **Migration:** replace sole reliance on `drift_state` with `source_status` + `sync_state` + `source_status_message`. Implementation ([#382](https://github.com/dustinestes/Hatchery/issues/382)) may keep a derived `drift_state` for one release for API/UI compatibility, mapped from the two axes - do not invent new meanings inside the old enum.

10. **Planning vs implementation.** [#370](https://github.com/dustinestes/Hatchery/issues/370) is the planning parent. Evaluate schema/state machine: [#382](https://github.com/dustinestes/Hatchery/issues/382). Cached UX: [#383](https://github.com/dustinestes/Hatchery/issues/383). Library → Content: [#384](https://github.com/dustinestes/Hatchery/issues/384).

11. **Library → Content** remains the north star for lifecycle chrome ([ADR-0016](0016-library-operator-plane.md)).

## Consequences

**Good**

- Reachability and sync comparison are separable; no junk-drawer `unknown`
- One validator/evaluate pass still fetches tip once, then sets both columns
- Operators get stable codes plus optional detail messages

**Neutral / follow-on**

- Schema migration and API shape land in [#382](https://github.com/dustinestes/Hatchery/issues/382)
- Remote rename vs delete remain indistinguishable (`missing`)
- Local rename / ghosts stay on [#361](https://github.com/dustinestes/Hatchery/issues/361)

**Bad / accepted cost**

- Two columns (+ message) instead of one; filters and tests grow
- Derived `drift_state` (if kept briefly) must not reintroduce the mixed model

## Alternatives considered

| Option | Why not |
|---|---|
| More values in a single `drift_state` | Still conflates reachability with compare |
| Keep path-gone / rate limit as `unknown` | Misnames known outcomes |
| Fold `missing` into `out_of_sync` | Inflates Alerts/auto-sync for paths that cannot pull |
| Fold `missing` into `orphan` | Mis-labels valid connection/binding ids |
| Separate network round-trip for sync after reachability | Rejected - one evaluate pass already has tip data |
| `sync_state` writable from UI | Rejected - validator/evaluate owns truth after Sync/pull |
