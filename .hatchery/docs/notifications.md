<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Notifications</h1>
<br clear="both">

Umbrella for operator-facing signals in Hatchery: **Alerts** (conditions that need attention), **Events** (hatch/provision transcript), and a future **Audit** trail. The sidebar group is labeled Notifications; each child concern has its own module, API, and pane.

<br>

## Contents

- [Contents](#contents)
- [Overview](#overview)
- [Separation of concerns](#separation-of-concerns)
- [Toasts](#toasts)
- [Alerts](#alerts)
  - [UI surfaces](#ui-surfaces)
  - [Lifecycle](#lifecycle)
  - [Background sync](#background-sync)
  - [Contributor tooling](#contributor-tooling)
- [Events](#events)
- [Audit (v2)](#audit-v2)

---

<br>

## Overview

Use **notifications** only where grouping the concerns makes sense (sidebar parent label, umbrella docs, `/notifications/...` route prefix). Alert-specific UI, code, and APIs use **alerts** — including the topbar bell and tray. Ephemeral **toasts** are a separate UI channel (`hatchery.showToast`) that never show Events or Audit. Hatch lifecycle uses **events** (`hatch_events`); inventory/CRUD history will use **audit** when v2 lands.

| Concern | What belongs | Surface |
|---|---|---|
| **Alerts** | Conditions that threaten Hatchery working: missing host tools, invalid Clutches, rare fundamental failures | Bell, tray, toasts (when new alerts arrive), Alerts pane, footer Nest indicator |
| **Toasts** | Ephemeral UI feedback (copy succeeded, import conflict, etc.) — **not** persisted | Bottom-right overlay via `hatchery.showToast` |
| **Events** | Under-the-hood hatch/provision transcript (`hatch_events`, including `Write-HatchEvent` script lines) | Events pane ([#114](https://github.com/dustinestes/Hatchery/issues/114)) |
| **Audit (v2)** | Who/what changed Clutches; VM removed/renamed; session archived | Not implemented yet — not toast spam |

<br>

---

<br>

## Separation of concerns

```
Notifications (sidebar group)
  ├─ Alerts   — validation / health (`/notifications/alerts`, `GET /api/alerts`)
  └─ Events   — hatch lifecycle feed (`/notifications/events` — UI in #114)
```

Umbrella routes stay under `/notifications/...`. Alert CRUD lives in `lib/alerts.py`. Event writers stay in `lib/hatch.py` (`add_event`).

**Toast vs Alerts tray:** painting a toast never inserts an Alerts DB row by itself. Alert polling may call `hatchery.showToast` when a *new* alert arrives so operators notice it; Import/copy/delete panes also call `showToast` for short-lived UI feedback without touching the tray. Alerts store the same **tier** vocabulary as toasts (`info` / `warning` / `alert`) via `record_alert(message, tier=...)`; polling passes that tier through to `showToast` and the tray badge.

<br>

---

<br>

## Toasts

Fixed bottom-right stack (`#toast-container` in `templates/ui/base.html`). Implemented in `static/app.js` as `hatchery.showToast` and styled in `static/style.css` (`.toast*`).

### API

```js
hatchery.showToast(message, tier?, durationMs?)
```

| Argument | Notes |
|---|---|
| `message` | Plain text shown in the toast body |
| `tier` | `'info'` \| `'warning'` \| `'alert'` (alias `'error'` → `alert`). Default `'alert'` |
| `durationMs` | Optional hold time before dismiss. Defaults: info **2200**, warning **4500**, alert **5000** |

Each toast shows a **tier label** (Info / Warning / Alert) plus an icon so meaning is not color-only. Alert-tier toasts use `role="alert"`; info/warning use `role="status"`. The container keeps `aria-live="polite"`. Enter/exit motion respects `prefers-reduced-motion`.

### When to use which

| Use | Prefer |
|---|---|
| Condition that needs attention until fixed (missing tool, invalid Clutch, import in progress) | `lib.alerts.record_alert` (bell + tray + pane); toast may appear via alert polling |
| Short UI confirmation or rejection (path copied, file exists, delete failed) | `hatchery.showToast` only |
| Hatch/provision transcript | Events pane — not toasts |

<br>

---

<br>

## Alerts

Alerts are stored in the `alerts` table in `hatchery.db`. The browser polls `GET /api/alerts` and updates toast overlay, bell badge, tray dropdown, and the Alerts pane without a full page refresh.

### UI surfaces

**Toast overlay** — brief banner in the bottom-right when new alerts arrive (via `hatchery.showToast(..., 'alert')`). Auto-dismiss uses the alert-tier default (~5s). Same component as UI-only toasts.

**Bell badge** — topbar control labeled **Alerts**; unread count of active alerts.

**Tray dropdown** — headed **Alerts**; recent alerts; “View all” links to `/notifications/alerts`.

**Alerts pane** — alert history, reverse-chronological (UI shows the newest 500; older rows remain in the DB). Filters: Active / Resolved only. Route: `/notifications/alerts`.

![Alerts pane — full table view](assets/screenshot_notifications_pane.png)

### Lifecycle

Alerts are written by calling `lib.alerts.record_alert(message, tier="alert")`. This inserts a row into the `alerts` table with:

- `created_at` — UTC ISO 8601 timestamp
- `message` — human-readable description
- `tier` — `info` \| `warning` \| `alert` (same as `hatchery.showToast`; default `alert`)
- `resolved = 0`, `resolved_at = NULL`

An alert is **active** while `resolved = 0`. It is **resolved** by the system (never by the user) when the condition that triggered it no longer exists. Resolution sets `resolved = 1` and `resolved_at` to the resolution timestamp.

Resolved alerts remain as historical records. They appear in the Alerts pane with a “Resolved” status badge and are excluded from the active alert count used by the bell badge and footer indicator. Hatchery does not auto-delete alert rows by count or age.

| State | Rendered as |
|---|---|
| `resolved = 0` | Active badge |
| `resolved = 1` | Resolved badge + timestamp |

### Background sync

Hatchery runs two sync functions at startup and then on every background cycle (controlled by the **Background Validation Interval** setting, default 60 seconds):

#### Requirements sync (`_sync_requirements`)

1. Checks which required host tools are currently present via `lib.requirements.check_all()`.
2. For each missing tool, records an alert prefixed with `"Missing requirement:"` if one is not already active.
3. For each present tool, resolves any active alert with that same prefix.

#### Clutch file sync (`_sync_clutches`)

1. Iterates every `.yaml` file in the clutches directory.
2. For each file, runs full schema and dependency validation via `clutch_lib.load()`.
3. On failure, records an alert prefixed with `"Invalid Clutch file: '<filename>'"` if one is not already active.
4. On success, resolves any active alert for that file.

Alerts for a deleted Clutch file are resolved immediately at delete time — not waiting for the next sync cycle.

#### Import copies (`lib/import_files.py`)

UI **Import** on Clutches, Media (ISO / VirtIO), and Automations → Scripts uploads files into the data directory. While the Nest is writing a batch, Hatchery records an active alert prefixed with `"Import in progress:"` at tier **info**. When the request finishes, that alert is resolved and a `"Import finished:"` trail alert is recorded as already resolved (history only — it does not keep the bell active) at tier **info** on full success or **warning** when files were skipped/failed. Conflicts refuse overwrite and never replace an existing basename.

The result: alert state in the database always reflects the current environment. If a missing tool is installed or a broken Clutch file is fixed, the alert is resolved on the next sync cycle without requiring a restart.

### Contributor tooling

A seed script inserts sample alerts for UI validation and screenshot capture. Seeded records are marked with `[seed]` so they can be identified and removed without touching real alert history.

```bash
# Insert the next curated alert (cycles through samples with each call)
uv run python .hatchery/tooling/seed_alerts.py seed

# Insert a custom message
uv run python .hatchery/tooling/seed_alerts.py seed "Missing requirement: 'virsh' is not installed"

# Insert all curated samples
uv run python .hatchery/tooling/seed_alerts.py seed all

# Remove all seeded alerts
uv run python .hatchery/tooling/seed_alerts.py clean
```

The script requires Hatchery to have been started at least once (so `hatchery.db` exists). It reads the same data directory configuration as the app.

<br>

---

## Events

Hatch / provision lifecycle and `Write-HatchEvent` script lines are stored in `hatch_events` and shown on the Events pane under `/notifications/events` ([#114](https://github.com/dustinestes/Hatchery/issues/114)). The pane lists active hatch VMs on the left and a live-updating chronological feed on the right (polls `GET /api/sessions/.../events`). Events do not drive the Alerts bell, tray, or toasts. Event rows for a session are purged when that session is archived — see [events.md — Retention](events.md#retention).

See [events.md](events.md) and [orchestration.md](orchestration.md).

<br>

---

## Audit (v2)

Clutch create/save/delete, VM cull/rename, and session archive are **not** alerts and are **not** written as toast-driving activity. A future audit trail will cover inventory and authoring changes without mixing them into the Alerts surfaces — tracked in [#164](https://github.com/dustinestes/Hatchery/issues/164).

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
