# ADR-0023: Settings SQLite revision reload across processes

- **Status:** Accepted
- **Date:** 2026-09-26
- **Issues:** [#439](https://github.com/dustinestes/Hatchery/issues/439); dual-surface [#336](https://github.com/dustinestes/Hatchery/issues/336) / [ADR-0022](0022-dual-surface-operator-discipline.md); partial writes [ADR-0015](0015-settings-partial-writes-worker-services.md)

## Context

Exportable Controller Settings live in SQLite `app_settings` and are bound into an in-memory `lib.config` snapshot for the long-lived `hatchery serve` (and any other long-lived Controller process). Operator CLI `settings set` (and product convenience writers such as `library enable|disable`) write SQLite via `update_settings` in a **separate process**. Without a reload signal, the UI kept showing stale values (for example `library_enabled`) until serve restarted.

External Settings YAML/git watch is a different problem ([#253](https://github.com/dustinestes/Hatchery/issues/253), parked). This ADR only covers **same data dir, multiple processes** sharing `hatchery.db`.

## Decision

1. Every Settings UPSERT through `_write_db_settings` bumps a meta row `_settings_rev` (integer JSON) in the **same transaction** as the product keys.
2. Each process tracks `_local_settings_rev`. On `get()` (after bind), if the DB revision differs, reload `_DB_SETTING_KEYS` from SQLite **into the existing** `_config` dict (preserve `get()` identity; do not rewrite `data_dir` / runtime overrides).
3. Writers that bump the rev in this process also update `_local_settings_rev` so they do not needlessly re-read.
4. Keep partial writes (`update_settings`) as the write API (ADR-0015). Do not resurrect full-snapshot clobber from background workers.
5. `_settings_rev` is not an exportable Setting and is not part of Settings YAML export/import.

## Consequences

- CLI `settings set` against the same data dir is visible to a running UI on the next `get()` / status poll / request that reads Settings - no serve restart.
- Every Settings write pays a small revision UPSERT; readers pay a cheap rev SELECT when already fresh.
- DB file mtime is not used (other tables change the file without Settings meaning).
- Does not push UI redraw beyond existing status surfaces; memory refresh is enough for the next render/API.

## Alternatives

| Option | Why not |
|---|---|
| SQLite file mtime | Noisy: nests, alerts, Library tables touch the same file |
| Always re-read all keys on every `get()` | Unnecessary I/O when unchanged |
| Only `@app.before_request` | Misses non-Flask long-lived readers; `get()` is the shared path |
| Push/websocket forced nav | Out of scope; status bus already polls plane status |

## Related docs

- Operator how-to: [`docs/settings.md`](../settings.md), [`docs/cli/settings.md`](../cli/settings.md)
- Code: `lib/config.py` (`ensure_settings_fresh`, `_write_db_settings`)
