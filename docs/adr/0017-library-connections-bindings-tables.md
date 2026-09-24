# ADR-0017: Library connections and bindings as first-class tables

- **Status:** Accepted
- **Date:** 2026-09-24
- **Issues:** [#367](https://github.com/dustinestes/Hatchery/issues/367); plane [#375](https://github.com/dustinestes/Hatchery/issues/375)
- **Related:** [ADR-0015](0015-settings-partial-writes-worker-services.md), [ADR-0016](0016-library-operator-plane.md), [ADR-0012](0012-library-cache-provenance-drift.md)
- **How-to:** [library.md](../library.md) (update when migration ships)
- **Code (target):** `lib/db.py` schema + migrate; accessors beside `lib/library_provenance.py`

## Context

Library connections and domain bindings live as JSON arrays in `app_settings` (`library_connections`, `library_script_bindings`, `library_clutch_bindings`, `library_media_bindings`). That:

- Couples Library config to Settings document reads/writes (clobber risk even after [ADR-0015](0015-settings-partial-writes-worker-services.md))
- Makes cascade, orphan, and listing-by-connection awkward compared to rows
- Does not scale as an enterprise connection registry

Provenance is already first-class SQLite (`library_cache_provenance`, [ADR-0012](0012-library-cache-provenance-drift.md)). Connections/bindings should match. UI ownership moves to Library → Connections ([ADR-0016](0016-library-operator-plane.md)).

## Decision

1. **Keep `library_enabled` in `app_settings`.** All other Library connection/binding configuration leaves Settings JSON.

2. **Tables** (names illustrative; implementer may adjust within these constraints):

| Table | Role |
|---|---|
| `library_connections` | One row per connection: stable `id`, label, type, provider, base_uri, token (or secret ref later), expires_at, kinds, enabled, timestamps |
| `library_bindings` | One row per binding: stable `id`, `connection_id`, domain (`scripts` / `clutches` / `media`), optional `media_target`, label, filter, enabled, timestamps |

3. **Integrity**

- Binding `connection_id` must reference an existing connection (enforce in app and/or SQLite FK).
- Provenance continues to store `connection_id` / `binding_id` as text ids; evaluate/orphan behavior unchanged in spirit ([ADR-0012](0012-library-cache-provenance-drift.md)).
- Indexes at minimum: bindings by `connection_id`, bindings by `domain` (+ media_target), connections by enabled/type as needed for list/validators.

4. **Writes are row-scoped.** Creating/updating/deleting a connection or binding must not rewrite unrelated Settings keys or dump the whole Library registry through `config.save()`. Align with partial-write lessons in ADR-0015.

5. **Migration:** On Controller upgrade, copy JSON arrays into tables idempotently; then stop reading those Settings keys (or read tables only). Preserve ids so provenance rows keep matching. Document rollback (export before migrate / keep JSON until verified) in the implementing PR.

6. **Cascade:** Default delete connection/binding leaves Cached files; provenance becomes orphan when ids disappear. Optional delete-attributed-cache remains an explicit operator choice (existing product rule).

7. **Backup / portability:** Settings YAML export may omit connection secrets policy as today, but must **document** that Library registry lives in SQLite after this ADR. Follow-on may add Library-aware export; do not silently drop connections on Settings import without a defined rule (implementing PR locks import behavior: reject, merge, or replace-Library-section).

8. **Concurrency:** Same Controller assumptions as Settings (single writer / worker services). No arbiter process mutates Library tables from a stale snapshot.

9. **UI:** Library → Connections reads/writes these tables ([ADR-0016](0016-library-operator-plane.md)). Settings → Library does not remain the editor.

10. **Scale goals:** Schema must tolerate many connections/bindings and future domains/providers without returning to Settings blobs. Avoid unbounded JSON columns for the registry itself; typed columns for queryable fields.

## Consequences

**Good**

- Library config matches provenance as relational data
- Safer edits; clearer cascade and listing
- Enterprise-shaped registry growth

**Neutral / follow-on**

- Secret storage may later move to a vault ([#259](https://github.com/dustinestes/Hatchery/issues/259)); token column remains v1
- Cleaners (#361) can target orphaned provenance against table ids
- Settings import/export contract needs an explicit Library clause when this ships

**Bad / accepted cost**

- One-time migration and dual-read window during rollout
- Contributors debugging must look at SQLite, not only Settings YAML

## Alternatives

| Alternative | Why not |
|---|---|
| Keep JSON in `app_settings` forever | Does not meet durability/scale bar; keeps Settings clobber surface |
| One `library_config` JSON file beside the DB | Still blob-shaped; weaker query/cascade than tables |
| Normalize tokens into a secrets table in the same PR | Valuable later; out of scope for first migration |
