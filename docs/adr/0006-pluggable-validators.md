# ADR-0006: Pluggable validators; Alerts ≠ validator runs

- **Status:** Accepted
- **Date:** 2026-09-19
- **Issue:** [#268](https://github.com/dustinestes/Hatchery/issues/268)
- **Code:** [`lib/validators/`](../../lib/validators/)
- **How-to:** [validators.md](../validators.md)

## Context

A private `_background_loop` in `hatchery.py` ran a fixed bundle on one `bg_interval` (requirements, clutches, hatch status, Nest SSH expiry). That cannot express Controller-only vs Nest-over-SSH cadences, Settings enable/disable per concern, or Library connection health without growing a catch-all.

We needed an extensibility boundary that:

1. Registers new health/requirements checks as plugins
2. Separates **findings** (bell) from **execution observability** (did the check run?)
3. Keeps hatch lifecycle polling out of operator-disableable health toggles

## Decision

1. New package [`lib/validators/`](../../lib/validators/): `BaseValidator`, context, registry, scheduler, settings, runs
2. Each check declares `id`, `scope` (`controller` \| `nest` \| `content`), defaults, and `run(ctx)`
3. **Two channels — do not conflate:**
   - **Alerts** — findings that need attention (bell / tray / toasts / Alerts pane)
   - **`validator_runs`** — scheduled or on-demand execution history (ok/error, summary, trigger)
4. Persist runs in SQLite (not memory-only `last_run`)
5. **Not a validator:** hatch lifecycle poller (`_sync_hatch_status`) stays app-owned — operators must not disable fledging by accident
6. Controller vs Nest requirement **bodies** (#208) and Nest reachability (#263) register as validators — they do not extend a private catch-all loop

Validators are the **gather** layer only ([ADR-0004](0004-status-surfaces-gather-store-poll.md)); they must not push to the DOM.

## Consequences

**Good**

- New checks = new module + register; Settings list is registry-driven
- Successful runs with no findings do not spam the Alerts bell
- On-demand `run_now` / Test connection share the same contract as the scheduler

**Neutral / follow-on**

- Per-validator enable, interval, and run-history retention in Settings
- Library connection health and Nest capability checks plug in later without reshaping the bus

**Bad / accepted cost**

- Contributors must not grow `_background_loop` for new health concerns
- Two UIs (Alerts vs Validators) require clear copy so operators do not confuse findings with run history

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep extending `_background_loop` | No per-check Settings; couples unrelated cadences |
| In-memory-only last_run | Lost across restarts; Notifications cannot show history |
| Make hatch poller a user-disableable validator | Operators can break fledging by turning it off |
| Write every finding only to `validator_runs` | Bell/tray need stable Alerts semantics ([ADR-0008](0008-alerts-events-audit-separation.md)) |
