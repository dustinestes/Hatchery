# ADR-0041: Nest Events transcript (Nest-scoped, parallel to hatch_events)

- **Status:** Accepted
- **Date:** 2026-10-20
- **Issues:** [#611](https://github.com/dustinestes/Hatchery/issues/611), parent [#215](https://github.com/dustinestes/Hatchery/issues/215)
- **Related:** [ADR-0008](0008-alerts-events-audit-separation.md), [ADR-0040](0040-nest-reported-nest-cache-sync.md), [#609](https://github.com/dustinestes/Hatchery/issues/609), [#345](https://github.com/dustinestes/Hatchery/issues/345); supersedes alerts-backed Nest tile [#539](https://github.com/dustinestes/Hatchery/issues/539)
- **How-to:** [nest-health.md](../nest-health.md) (Events tile); [database.md](../schema/database.md) (`nest_events`)

## Context

Nest Health, nest_cache sync, transport, and later Nest jobs (#345 / #609) need an append-only Nest-plane transcript. Hatch/provision lines already live in ``hatch_events`` (ADR-0008). Alerts remain for conditions that threaten working Hatchery. An Alerts-backed Nest "Events" tile (#539) would conflate threats with transcripts and would not hold Nest agent progress lines.

## Decision

1. **Store:** SQLite table ``nest_events`` keyed by ``nest_id`` (not session/VM). Module ``lib/nest_events.py``.
2. **Columns:** ``id``, ``nest_id``, ``source`` (``controller`` \| ``nest``), ``topic`` (``health`` \| ``transport`` \| ``cache_sync`` \| ``job`` \| ``general``), ``level`` (``INFO`` \| ``WARN`` \| ``ERROR``), optional ``component``, ``message``, optional ``ref`` (future job id), ``received_at`` (Controller store UTC).
3. **Retention:** Delete all rows for a Nest when that Nest is removed from the registry. No age/count FIFO (same Maintenance policy as the rest of ``hatchery.db``).
4. **Surfaces (v1):** Nest detail **Events** tile only; ``GET``/``POST /api/nests/<id>/events``; CLI ``hatchery nest events``. Do **not** merge into global ``/notifications/events`` / ``hatch_events``.
5. **Writers (v1):** Controller best-effort lines from Nest Health (``topic=health``) and nest_cache Check sync (``topic=cache_sync``). ``POST`` ingest accepts Nest-sourced batches for #609/#345.
6. **Not Alerts:** Nest Events is not an Alerts feed. [#539](https://github.com/dustinestes/Hatchery/issues/539) is superseded.

## Consequences

**Good**

- Clear Nest vs Hatch plane Events vocabulary
- Ready ingest contract for Nest pull / job agent
- Dual-surface UI + CLI (ADR-0022)

**Neutral / follow-on**

- Global Nest Events console later if needed
- Richer ``topic`` / ``ref`` usage when #609/#345 land

**Bad / accepted cost**

- Operators look at Nest detail for Nest lines and Notifications → Events for hatch lines

## Alternatives considered

| Alternative | Why not |
|---|---|
| Alerts-backed Nest Events tile (#539) | Conflates threats with transcripts; no Nest agent progress |
| Rows in ``hatch_events`` | Session/VM scoped; wrong plane |
| Sync-only log on Cache tile | Footguns Nest Health / transport / jobs |
| Age or hard row caps in v1 | Contradicts database Maintenance policy |
