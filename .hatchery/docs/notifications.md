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

Use **notifications** only where grouping the concerns makes sense (sidebar parent label, umbrella docs, `/notifications/...` route prefix). Alert-specific UI, code, and APIs use **alerts** — including the topbar bell, tray, and toasts, which never show Events or Audit. Hatch lifecycle uses **events** (`hatch_events`); inventory/CRUD history will use **audit** when v2 lands.

| Concern | What belongs | Surface |
|---|---|---|
| **Alerts** | Conditions that threaten Hatchery working: missing host tools, invalid Clutches, rare fundamental failures | Bell, tray, toasts, Alerts pane, footer Nest indicator |
| **Events** | Under-the-hood hatch/provision transcript (`hatch_events`, including `Write-HatchEvent` script lines) | Events pane ([#114](https://github.com/dustinestes/Hatchery/issues/114)) |
| **Audit (v2)** | Who/what changed Clutches; VM removed/renamed; session archived | Not implemented yet — not toast spam |

<br>

---

## Separation of concerns

```
Notifications (sidebar group)
  ├─ Alerts   — validation / health (`/notifications/alerts`, `GET /api/alerts`)
  └─ Events   — hatch lifecycle feed (`/notifications/events` — UI in #114)
```

Umbrella routes stay under `/notifications/...`. Alert CRUD lives in `lib/alerts.py`. Event writers stay in `lib/hatch.py` (`add_event`).

<br>

---

## Alerts

Alerts are stored in the `alerts` table in `hatchery.db`. The browser polls `GET /api/alerts` and updates toast overlay, bell badge, tray dropdown, and the Alerts pane without a full page refresh.

### UI surfaces

**Toast overlay** — brief banner in the bottom-right when new alerts arrive. Auto-dismiss after 4 seconds. Styled with `.toast--alert`.

**Bell badge** — topbar control labeled **Alerts**; unread count of active alerts.

**Tray dropdown** — headed **Alerts**; recent alerts; “View all” links to `/notifications/alerts`.

**Alerts pane** — full alert history (up to 500 rows), reverse-chronological. Filters: Active / Resolved only. Route: `/notifications/alerts`.

![Alerts pane — full table view](assets/screenshot_notifications_pane.png)

### Lifecycle

Alerts are written by calling `lib.alerts.record_alert(message)`. This inserts a row into the `alerts` table with:

- `created_at` — UTC ISO 8601 timestamp
- `message` — human-readable description
- `resolved = 0`, `resolved_at = NULL`

An alert is **active** while `resolved = 0`. It is **resolved** by the system (never by the user) when the condition that triggered it no longer exists. Resolution sets `resolved = 1` and `resolved_at` to the resolution timestamp.

Resolved alerts remain as historical records. They appear in the Alerts pane with a “Resolved” status badge and are excluded from the active alert count used by the bell badge and footer indicator.

After every insert, rows beyond the 500-row cap are trimmed. See [`schema/database.md`](schema/database.md).

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

Alerts for a deleted Clutch file are resolved immediately at delete time — not waiting for the next background cycle.

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

Hatch / provision lifecycle and `Write-HatchEvent` script lines are stored in `hatch_events` and shown on the Events pane under `/notifications/events` ([#114](https://github.com/dustinestes/Hatchery/issues/114)). The pane lists active hatch VMs on the left and a live-updating chronological feed on the right (polls `GET /api/sessions/.../events`). Events do not drive the Alerts bell, tray, or toasts.

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
<div align="right">Where environments hatch</div>
<br clear="both">
