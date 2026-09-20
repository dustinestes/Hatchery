# ADR-0012: Library cache provenance + drift sync

- **Status:** Accepted
- **Date:** 2026-09-19
- **Issues:** [#308](https://github.com/dustinestes/Hatchery/issues/308)
- **Code:** [`lib/library_provenance.py`](../../lib/library_provenance.py), [`lib/library_drift.py`](../../lib/library_drift.py), validator `library_cache_drift`
- **How-to:** [library.md — Cache provenance and drift](../library.md#cache-provenance-and-drift-308)
- **Related:** [ADR-0009](0009-library-git-checkout-cache.md), [ADR-0010](0010-library-forge-providers.md), [ADR-0011](0011-library-consume-only-no-clutch-roundtrip.md), [ADR-0006](0006-pluggable-validators.md)

## Context

Library pull is **create-only** into the operator domain cache. Once a basename exists, source updates do not overwrite it — operators can hatch stale Scripts / Clutches / Media with no signal. Local edits to attributed cache files are equally invisible without a durable compare.

Drift detection needs durable attribution of cached files → Library source. Re-resolve-by-bindings alone is fragile (filters change, multiple bindings). Forge list often omits Hatchery SHA-256 (git blob SHAs ≠ content SHA-256 — ADR-0010). Downloading media bodies solely to hash them for compare is unacceptable. Forge tip checks that hit the network once per file burn API rate limits.

## Decision

1. **SQLite provenance** (`library_cache_provenance`) keyed by `(domain, media_target, cache_name)` with **`connection_id` / `binding_id`** (stable ids, not labels). Location-prefixed digest columns:

| Column | Role |
|---|---|
| `cache_sha256` | Observed Hatchery SHA-256 of cache bytes (refreshed each evaluate) |
| `cache_sha256_synced` | Anchor: cache SHA at last successful sync/pull |
| `source_digest` | Observed remote tip (refreshed each evaluate) |
| `source_digest_synced` | Anchor: remote tip at last successful sync/pull |
| `source_digest_kind` | Tip alphabet: `sha256`, `git_blob`, or `size_mtime` |

2. **Bidirectional drift** (evaluate owns truth): refresh observed columns, then:

   - `cache_drifted` = `cache_sha256 != cache_sha256_synced`
   - `source_drifted` = `source_digest != source_digest_synced`
   - `live_mismatch` = when tip kind is content-addressable (`sha256` / `git_blob`), cache content identity ≠ observed `source_digest` (skipped for `size_mtime`)
   - `out_of_sync` if any of the three; promote `_synced` anchors only when evaluate reaches `in_sync`

3. **Files never pulled via Library stay local** (no row → no sync / no orphan).

4. **One tip-identity story per connection type** (all domains share it — no mixed strategies within a type):

| Type | Tip identity for drift |
|---|---|
| `path` | `size` + `mtime` (`size_mtime`) |
| `api` | Metadata SHA-256 when present (`sha256`); else unknown — no download |
| `forge` | Git blob SHA from Trees/Contents (`git_blob`) — no raw download for drift |
| `git` | Blob id from checkout tree (`git_blob`) — no content-hash for drift |
| `https` | Checksum header on HEAD if present; else unknown — no GET for drift |

5. **Never download an artifact body solely to compare digests.** Sync (manual or auto) is the only overwrite/download path into the operator cache.

6. **Sync = pull bytes then evaluate** for that row. Sync does not force `in_sync` or resolve Alerts; evaluate updates digests, `drift_state`, and domain Alert reconcile.

7. **Forge tip resolution is batched** per connection per drift pass (one Trees fetch maps all paths). Single-row evaluate may use a cheap per-path Contents tip. Rate limits (403/429) → `unknown`, no retry storm.

8. **Delete connection/binding:** default leave Cached files; provenance becomes **orphan** when ids are missing. Optional confirm toggle (**default off**) also deletes attributed cache files + rows.

9. **Orphan UX:** warning; **re-attach** modal (pick connection/binding, optional `relative_path`, Test, rewrite ids).

10. **Validator `library_cache_drift`:** interval + optional **auto_sync**. Manual mode → at most **one Alert per domain** with count. Auto-sync on → sync out-of-sync items then evaluate; **no** drift Alerts.

11. Sync updates local cache only — **no forge/git push** (ADR-0011).

## Consequences

**Good**

- Operator model matches desired-state systems: measure both sides, compare, then act
- Local edits and source moves both surface as out of sync
- Sync cannot lie about health without evaluate agreeing
- Forge API use scales with connections, not attributed file count

**Neutral / follow-on**

- Path drift is coarse (mtime/size can false-positive); accepted for a rudimentary source
- Pre-#308 pulls have no provenance until re-pulled or re-attached
- Cross-interval ETag tip cache is optional later

**Bad / accepted cost**

- Content-addressable live match needs a cheap local identity (SHA-256 or git-blob of cache bytes) each evaluate
- HTTPS without checksum headers stays `unknown`
- Unauthenticated GitHub still rate-limits if the validator interval is aggressive
