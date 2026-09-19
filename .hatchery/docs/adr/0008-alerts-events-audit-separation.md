# ADR-0008: Alerts vs Events vs Audit (Notifications umbrella)

- **Status:** Accepted
- **Date:** 2026-09-19
- **Issues:** [#158](https://github.com/dustinestes/Hatchery/issues/158) (alerts-only redesign; absorbed [#147](https://github.com/dustinestes/Hatchery/issues/147))
- **How-to:** [notifications.md](../notifications.md)

## Context

An earlier “notifications / activity” path mixed validation failures, hatch lifecycle lines, and inventory CRUD into one toast/bell stream. That made the bell noisy, blurred product language, and fought a clear Events pane for hatch transcripts.

We needed an explicit separation of concerns so:

1. The bell only rings for conditions that threaten Hatchery working
2. Hatch/provision transcripts have a dedicated home
3. Inventory / Clutch CRUD audit is not toast spam

## Decision

| Concern | What belongs | Primary surface |
|---|---|---|
| **Alerts** | Conditions that threaten working Hatchery (missing tools, invalid Clutches, Nest reachability, …) | Bell, tray, toasts, Alerts pane, footer chips |
| **Events** | Hatch / provision transcript (`hatch_events`, script `Write-HatchEvent` lines) | Events pane |
| **Audit (v2)** | Who/what changed Clutches; Cull / rename / session archive — not validation, not provision log | Deferred; not toast spam |

**Naming:** use **Notifications** only for the **umbrella** sidebar group and group docs. Alert-specific modules/APIs use **alerts** (`lib/alerts.py`, `/api/alerts`, …). Do not keep alert-only artifacts named `notifications`.

Remove the activity path; do not mirror hatch lifecycle into Alerts toasts. Validator **runs** are observability of checks, not Alerts ([ADR-0006](0006-pluggable-validators.md)). Status display still follows gather → store → poll ([ADR-0004](0004-status-surfaces-gather-store-poll.md)).

## Consequences

**Good**

- Bell stays actionable; Events owns lifecycle narrative
- Clear vocabulary for docs, APIs, and seeds
- Audit can land later without reopening toast design

**Neutral / follow-on**

- Until Events UX is rich, operators may miss global “VM fledged” toasts — intentional
- Validators pane shows run history separately from Alerts findings

**Bad / accepted cost**

- Three mental models (Alerts / Events / Audit) instead of one inbox
- Contributors must pick the right channel; wrong choice regresses noise

## Alternatives considered

| Alternative | Why not |
|---|---|
| Single activity + alerts inbox | Noisy bell; conflates threats with transcripts and CRUD |
| Keep alert code named `notifications` | Ambiguous once Events/Audit exist under the same umbrella |
| Toast every hatch lifecycle line | Duplicates Events; trains operators to ignore the bell |
| Put audit rows in Alerts | Not “threatens working Hatchery”; belongs in v2 audit |
