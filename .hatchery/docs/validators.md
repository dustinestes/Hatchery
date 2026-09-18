<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Validators</h1>
<br clear="both">

Pluggable background health checks for the Hatchery Controller, Nests, and content ([#268](https://github.com/dustinestes/Hatchery/issues/268)).

<br>

## Contents

- [Contents](#contents)
- [Two channels](#two-channels)
- [Contract](#contract)
- [Status surfaces](#status-surfaces)
- [Settings](#settings)
- [Notifications](#notifications)
- [Built-in validators](#built-in-validators)
- [Adding a validator](#adding-a-validator)

---

<br>

## Two channels

| Channel | Purpose |
|---|---|
| **Alerts** | Findings that need attention (missing tool, invalid Clutch) — bell / tray |
| **Validator runs** (`validator_runs`) | History of each validation execution — Notifications → Validators |

A successful run that opens Alerts still records `status=ok` on the run (the validator completed). `status=error` means the validator itself failed.

<br>

## Contract

Package: [`lib/validators/`](../../lib/validators/).

- `BaseValidator` — `id`, `title`, `description`, `scope` (`controller` \| `nest` \| `content`), defaults, `run(ctx) -> summary`
- `ValidatorContext` — data dir, alert helpers, optional `nest_id` / `trigger`
- Registry + scheduler — per-validator enable / interval; hatch lifecycle polling stays separate (`bg_interval`)
- `run_validator(id, trigger=…)` — schedule, manual, or connection

<br>

## Status surfaces

Validators are the **gather** layer only. They must not push to the DOM. Findings land in Alerts (and run history in `validator_runs`); the Controller UI **surfaces** poll stored state through `hatchery.refreshStatusSurfaces` / `onStatusTick` ([notifications.md — Status surfaces](notifications.md#status-surfaces), [#282](https://github.com/dustinestes/Hatchery/issues/282)).

When adding pane UI that should stay fresh (Validators filters [#280](https://github.com/dustinestes/Hatchery/issues/280), Libraries chip [#254](https://github.com/dustinestes/Hatchery/issues/254)), subscribe to the status tick — do not add another `setInterval` for health.

<br>

## Settings

**Settings → General → Validators**: enable, interval (min 10s), run-history retention (10–500 per validator, default 50). Legacy `bg_interval` still controls the Hatch status poller and seeds validator intervals once via `migrate_bg_interval()`.

<br>

## Notifications

**Notifications → Validators** lists recent runs (time, validator, status, tier, trigger, message). Does not drive the Alerts bell.

<br>

## Built-in validators

| Id | Status |
|---|---|
| `controller_requirements` | Active — Controller-plane tools (SSH client when Remotes exist; optional pwsh) |
| `clutch_files` | Active |
| `nest_key_expiry` | Active |
| `nest_reachability` | Active — endpoint TCP then Nest transport; result carries `endpoint` / `transport` reason |
| `nest_capability` | Active — provider-declared Nest tools (Local on-box; Remote over transport). **Gated by reachability** on Remotes ([#286](https://github.com/dustinestes/Hatchery/issues/286)): unreachable / never-probed Nests skip capability and clear Nest capability Alerts |
| `library_connections` | Stub — [#254](https://github.com/dustinestes/Hatchery/issues/254) |

<br>

## Adding a validator

1. Subclass `BaseValidator` and implement `run`.
2. `register()` it from `lib/validators/builtins.py` (or import-time registration).
3. Record findings with `ctx.record_alert` / `resolve_alerts_by_prefix`.
4. Update this doc and the provider/architecture docs if Nest-related.

Do **not** add new private loops in `hatchery.py` for health checks.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
