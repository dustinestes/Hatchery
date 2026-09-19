# ADR-0004: Status surfaces — gather → store → poll

- **Status:** Accepted
- **Date:** 2026-09-19
- **Issue:** [#282](https://github.com/dustinestes/Hatchery/issues/282)
- **How-to:** [notifications.md — Status surfaces](../notifications.md#status-surfaces), [validators.md](../validators.md)

## Context

Controller UI must show health (Alerts bell, footer chips, Validators pane, Library chips) without turning Hatchery into a SPA or taking a WebSockets dependency in v1. If each surface re-ran health logic, validators and Nest checks would duplicate, race, and diverge.

We needed a contract that:

1. Separates **probing the world** from **what the DOM shows**
2. Persists findings so restarts and multiple surfaces share one truth
3. Lets panes subscribe to a single client refresh bus instead of inventing timers

## Decision

Controller UI health is three layers:

| Layer | Role |
|---|---|
| **Gather** | Probe / check (validators; Hatch lifecycle poller stays separate) |
| **Store** | Persist findings and thin status (`alerts`, `validator_runs`, Nest reachability snapshot, …) |
| **Surface** | Read/poll stored state; decide what to show |

Surfaces **must not** invent health logic or re-run checks. Client bus: `hatchery.refreshStatusSurfaces` / `hatchery.onStatusTick` in `static/app.js`. Prefer Alerts (+ live Nest registry) for footer rollups; do not invent a third store per chip.

## Consequences

**Good**

- Validators and Nest checks write once; bell, tray, footer, and panes stay consistent
- New chips subscribe to the bus instead of adding `setInterval` loops
- Vanilla HTML/JS constraint is preserved

**Neutral / follow-on**

- Optional later `GET /api/status-bundle` or SSE — not required for v1
- Nest reachability may keep a thin snapshot between validator ticks (documented dual read)

**Bad / accepted cost**

- Surfaces can lag gather by one poll interval
- Contributors must resist “just call virsh from the footer”

## Alternatives considered

| Alternative | Why not |
|---|---|
| WebSockets push from gather to DOM | Extra stack; not needed for v1 poll cadence |
| JS framework / SPA rewrite | Conflicts with Hatchery’s vanilla UI constraint |
| Each surface runs its own health checks | Duplicates work; inconsistent badges |
| Fold hatch lifecycle Events into validators | Different concern; operators must not disable fledging by accident ([ADR-0006](0006-pluggable-validators.md)) |
