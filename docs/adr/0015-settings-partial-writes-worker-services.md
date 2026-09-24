# ADR-0015: Partial Settings writes and worker-only runtime services

- **Status:** Accepted
- **Date:** 2026-09-22
- **Issues:** [#366](https://github.com/dustinestes/Hatchery/issues/366); follow-on Library tables [#367](https://github.com/dustinestes/Hatchery/issues/367)
- **How-to:** Settings live in SQLite `app_settings`; launch: [ADR-0013](0013-hatchery-cli-launch-and-operator.md)

## Context

`hatchery serve` runs gunicorn (arbiter + worker). Module import used to start the hatch poller and validator scheduler in the process that imported the app (the arbiter). HTTP requests run in the worker.

Background writers (especially nest reachability) called `config.save({**config.get(), ...})`, which UPSERTed **every** known Settings key from that process’s in-memory snapshot. The arbiter’s stale snapshot periodically overwrote the worker’s Library connections, bindings, and retention - Settings UI looked correct while `hatchery.db` did not keep edits (file “blinks” on each tick).

## Decision

1. **Partial writes:** Callers that change one (or a few) Settings keys must use `config.update_settings({...})`, which UPSERTs only those keys and updates only those keys in memory. Full `config.save()` remains for intentional whole-form Settings POSTs.
2. **Worker-only runtime services:** Do not start the hatch poller or validator scheduler at import time. Start them via `hatchery.start_runtime_services()` from gunicorn `post_fork` (`hatchery serve`) and lazily from `@app.before_request` (raw `gunicorn hatchery:app` / tests).
3. **Library config in `app_settings` JSON** was transitional; connections/bindings move to first-class tables ([ADR-0017](0017-library-connections-bindings-tables.md), [#367](https://github.com/dustinestes/Hatchery/issues/367)). Keep `library_enabled` as an app setting. Operator UI: [ADR-0016](0016-library-operator-plane.md).

## Consequences

- Background reachability ticks cannot clobber Library or retention.
- Arbiter no longer runs competing schedulers against the worker’s Settings memory.
- Contributors using raw gunicorn still get services on first request.
- Follow-on: Library connection/binding tables reduce reliance on Settings JSON blobs (#367).

## Alternatives

- Single-process server only (no gunicorn workers) - rejects contributor/production serve shape in ADR-0013.
- SQLite row locking / leader election for Settings - heavier than partial writes + worker-only services.
