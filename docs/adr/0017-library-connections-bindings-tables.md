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

Controller vs Nest also changes backup expectations: the Controller owns the data directory (`hatchery.db`, domain caches, clone cache). Portability is “point a Controller at a backed-up data dir,” not a Settings YAML dump of the Library registry.

## Decision

1. **Keep `library_enabled` in `app_settings`.** All other Library connection/binding configuration leaves Settings JSON.

2. **Three registry tables** plus existing provenance (no Settings blob):

| Table | Role |
|---|---|
| `library_connections` | Connection registry (auth + reachability identity) |
| `library_connection_kinds` | Junction: which artifact kinds a connection serves |
| `library_bindings` | Domain locators under a connection |
| `library_cache_provenance` | Unchanged ownership ([ADR-0012](0012-library-cache-provenance-drift.md)); stores `connection_id` / `binding_id` as **soft refs** (TEXT, no FK) so delete-connection can orphan cache intentionally |

3. **Integrity and indexes** - see [Schema](#schema-locked-for-367) below.

4. **Writes are row-scoped.** Creating/updating/deleting a connection or binding must not rewrite unrelated Settings keys or dump the whole Library registry through `config.save()`. Align with partial-write lessons in ADR-0015.

5. **Migration:** On Controller upgrade, copy JSON arrays into tables idempotently; then delete the four Settings keys. Preserve ids so provenance rows keep matching. Rollback: restore the data directory (or DB file) from backup; do not rely on Settings YAML round-trip for the registry.

6. **Cascade (product):**

| Delete | Registry rows | Provenance / Cached files |
|---|---|---|
| Connection | **Immediate hard-delete** of the connection row; kinds junction and bindings cascade (`ON DELETE CASCADE`) | Default: leave files; provenance becomes **orphan**. Optional operator toggle deletes attributed cache (existing UX) |
| Binding | Immediate hard-delete of that binding row | Same orphan / optional attributed-cache delete |

No `deleted_at` tombstones on registry tables. Soft-delete would only complicate Cleaners and UI without a restore product.

7. **Backup / portability (Controller data dir):**

- **Primary:** back up the Controller **data directory** (includes `hatchery.db`, domain caches, `{data_dir}/library/git/`, etc.) and reconnect a Controller to that path (`--data-dir` / Settings data dir). That is the supported restore story after Nest/Controller split.
- Settings YAML export includes `library_enabled` only (not connection tokens, not registry rows).
- Legacy `library_*` arrays in an old Settings document are **ignored with a warning** - import must not wipe the SQLite registry.
- No separate Library YAML/JSON export API in #367. A future “dev tool” backup surface may exist; it is out of scope here and must not redefine Settings export as the registry vehicle.

8. **Concurrency:** Same Controller assumptions as Settings (single writer / worker services). No arbiter process mutates Library tables from a stale snapshot.

9. **UI:** Library → Connections reads/writes these tables ([ADR-0016](0016-library-operator-plane.md)). Settings → Library is transitional until that pane ships.

10. **Kinds are relational.** Use junction `library_connection_kinds`, not a `kinds_json` blob, so validators and Connections UI can `JOIN` / filter by kind in SQL.

11. **Tokens:** plaintext `token` TEXT on `library_connections` for v1 (matches today’s Settings storage). Never log. Vault / secret-ref later ([#259](https://github.com/dustinestes/Hatchery/issues/259)).

12. **Cleaners vs deletes:** Registry CRUD uses **immediate hard delete**. Cleaners ([#361](https://github.com/dustinestes/Hatchery/issues/361)) are for **orphaned cache files / provenance rows** left behind after connection or binding remove (and related drift hygiene) - not for replaying soft-deleted DB rows. Typical pattern: delete registry row now → optional attributed-cache purge in the same operator action → leftover orphans are Cleaner fodder.

## Schema (locked for #367)

Canonical operator dicts today (`parse_connections` / `parse_*_bindings`) are the migration source of truth. API-facing dicts still expose `kinds: list[str]`; persistence splits them into the junction.

### `library_connections`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | TEXT | NOT NULL | - | PK; stable 12-hex (or existing Settings id). Never renumber |
| `label` | TEXT | NOT NULL | - | Required; operator display name |
| `type` | TEXT | NOT NULL | - | `path` \| `https` \| `git` \| `api` \| `forge` (CHECK) |
| `provider` | TEXT | NOT NULL | `''` | Required when type is `api` or `forge`; empty otherwise |
| `base_uri` | TEXT | NOT NULL | - | Path or URL |
| `token` | TEXT | NOT NULL | `''` | Secret material v1 (plaintext in DB). Never log. Vault later (#259) |
| `expires_at` | TEXT | NULL | NULL | ISO **date** (`YYYY-MM-DD`) or NULL |
| `enabled` | INTEGER | NOT NULL | `1` | 0/1 |
| `created_at` | TEXT | NOT NULL | - | UTC ISO-8601 `…Z` |
| `updated_at` | TEXT | NOT NULL | - | UTC ISO-8601 `…Z` |

Indexes:

- PK on `id`
- `idx_library_connections_enabled` on `(enabled)` (validator / footer rollups)
- `idx_library_connections_type` on `(type)`

### `library_connection_kinds`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `connection_id` | TEXT | NOT NULL | - | FK → `library_connections(id)` **ON DELETE CASCADE** |
| `kind` | TEXT | NOT NULL | - | `scripts` \| `clutches` \| `media` \| `packages` (CHECK; same closed set as today’s `CONNECTION_KINDS`) |

Constraints / indexes:

- PK `(connection_id, kind)`
- Index on `(kind)` for “connections that serve scripts” listing
- Write path requires **at least one** kind row per connection (app-enforced; optional CHECK via trigger not required)

### `library_bindings`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | TEXT | NOT NULL | - | PK; stable id |
| `connection_id` | TEXT | NOT NULL | - | FK → `library_connections(id)` **ON DELETE CASCADE** |
| `domain` | TEXT | NOT NULL | - | `scripts` \| `clutches` \| `media` (CHECK) |
| `media_target` | TEXT | NOT NULL | `''` | `''` for non-media; `iso` \| `virtio` when domain=`media` (CHECK) |
| `label` | TEXT | NOT NULL | - | Operator display; defaults to filter at write if blank |
| `filter` | TEXT | NOT NULL | `'*'` | Path glob / locator (fnmatch story unchanged) |
| `enabled` | INTEGER | NOT NULL | `1` | 0/1 |
| `created_at` | TEXT | NOT NULL | - | UTC ISO-8601 |
| `updated_at` | TEXT | NOT NULL | - | UTC ISO-8601 |

Indexes:

- PK on `id`
- `idx_library_bindings_connection` on `(connection_id)`
- `idx_library_bindings_domain` on `(domain, media_target)`
- Optional: `(connection_id, domain)` for Connections admin right pane

No UNIQUE on `(connection_id, domain, filter)` - duplicate filters with different labels are allowed.

### Provenance relationship

Do **not** add FK from `library_cache_provenance.connection_id` / `binding_id` to the registry. Orphan-on-delete is a product feature; FK `ON DELETE RESTRICT` would block connection remove, and `ON DELETE SET NULL` would need nullable connection_id (today required on pull). Soft refs + evaluate orphan logic stay.

### SQLite pragmas

Registry writes use connections with `PRAGMA foreign_keys = ON` (same as other Hatchery DB accessors going forward).

## Locked decisions (schema planning)

| # | Topic | Choice |
|---|---|---|
| 1 | **Kinds storage** | **(B)** junction `library_connection_kinds` |
| 2 | **Token column** | **(A)** plaintext `token` TEXT; vault later |
| 3 | **Backup / export** | **Data-dir backup** is the Controller restore story. Settings YAML is not the registry vehicle; ignore legacy `library_*` keys on Settings import. No Library export API in #367 |
| 4 | **Soft-delete** | **Hard delete only** (immediate). Cleaners target orphaned cache/provenance, not tombstoned registry rows |
| 5 | **Id format** | Existing `new_id()` 12-hex |

## Sketch vs this design

Branch `feat/367-library-connection-tables` sketched two tables with `kinds_json`. After locks:

| Keep | Adjust |
|---|---|
| Two-table core + soft provenance refs | Drop `kinds_json`; add `library_connection_kinds` |
| Migrate-then-drop Settings keys | Same |
| Row accessors / config rewires | Load/save kinds via junction |
| CASCADE on bindings | CASCADE kinds too |
| - | NOT NULL defaults, CHECK enums, `enabled`/`type` indexes, `PRAGMA foreign_keys` |

**Verdict:** keep the branch as base; replace kinds persistence; tighten constraints. Not a full scrap.

## Consequences

**Good**

- Library config matches provenance as relational data
- Safer edits; clearer cascade and listing
- SQL-friendly kind filters for validators and admin UI
- Backup story matches Controller data-dir ownership

**Neutral / follow-on**

- Secret storage may later move to a vault ([#259](https://github.com/dustinestes/Hatchery/issues/259))
- Cleaners (#361) reclaim orphaned provenance / cache after hard deletes
- Optional future Controller backup tooling still copies (or archives) the data dir - not Settings YAML alone

**Bad / accepted cost**

- One-time migration and dual-read window during rollout
- Contributors debugging must look at SQLite, not only Settings YAML
- Plaintext tokens in DB until vault work
- Junction writes are slightly more code than a JSON column

## Alternatives

| Alternative | Why not |
|---|---|
| Keep JSON in `app_settings` forever | Does not meet durability/scale bar; keeps Settings clobber surface |
| One `library_config` JSON file beside the DB | Still blob-shaped; weaker query/cascade than tables |
| `kinds_json` TEXT on connections | Rejected in planning - prefer JOIN/filter by kind |
| Normalize tokens into a secrets table in the same PR | Valuable later; out of scope for first migration |
| FK provenance → bindings | Breaks intentional orphan-on-delete |
| Separate tables per domain (`library_script_bindings`, …) | Three near-identical schemas; domain is a column |
| Soft-delete / `deleted_at` on registry | No restore product; Cleaners belong on orphans, not tombstones |
| Settings YAML as Library backup | Wrong layer after Controller vs Nest; data dir is the unit of restore |
