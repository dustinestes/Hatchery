<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Notifications</h1>
<br clear="both">

How Hatchery surfaces environment alerts and activity events — tiers, lifecycle, UI components, and background sync.

<br>

## Contents

- [Contents](#contents)
- [Overview](#overview)
- [Tiers](#tiers)
- [UI Components](#ui-components)
  - [Toast Overlay](#toast-overlay)
  - [Bell Badge](#bell-badge)
  - [Tray Dropdown](#tray-dropdown)
  - [Sidebar navigation](#sidebar-navigation)
  - [Alerts Pane](#alerts-pane)
  - [Events Pane](#events-pane)
- [Lifecycle](#lifecycle)
  - [Alerts](#alerts)
  - [Activity](#activity)
  - [Status matrix](#status-matrix)
- [Background Sync](#background-sync)
- [Contributor Tooling](#contributor-tooling)

---

<br>

## Overview

Hatchery uses a lightweight notification system to communicate two categories of events: environment alerts (missing host requirements, invalid Clutch files) and activity events (VMs hatched, Clutch files exported). Both categories are served from the same `/api/notifications` endpoint and drive the same UI surfaces.

Alerts are stored in the `alerts` table and activity in the `activity` table in `hatchery.db`. The browser polls `/api/notifications` on every page load and updates all UI surfaces — toast overlay, bell badge, tray dropdown, and the Alerts pane — without requiring a page refresh.

<br>

---

## Tiers

| Tier | Meaning | Source | Resolution |
|---|---|---|---|
| `alert` | Environment is degraded — a required tool is missing, or a Clutch file is invalid | Background sync (startup + periodic) | Auto-resolved when the condition clears on the next sync cycle |
| `activity` | Something happened — a VM was hatched, a Clutch was exported | User action | Immutable; no lifecycle actions |

**Alerts** are system-owned. They are recorded at startup and re-evaluated on every background sync cycle, and resolved automatically when the triggering condition is gone. An alert is active until the system resolves it — there is no user dismiss action.

**Activity** notifications are action-owned. Each user action that completes successfully (hatch, export, append) records an activity entry. These accumulate as an immutable audit trail; they have no lifecycle state and cannot be dismissed or resolved.

<br>

---

## UI Components

There are four surfaces that show notification state (toast, bell, tray, Alerts pane). All four derive from the same `/api/notifications` poll. The Events pane is a separate surface under the same sidebar group and reads from `hatch_events` (see [events.md](events.md)).

### Toast Overlay

A brief banner that appears in the bottom-right corner when new notifications arrive. Toasts auto-dismiss after 4 seconds. Alerts render with a distinct color; activity notifications render neutral.

<table><tr>
<td><img src="assets/screenshot_notifications_toast_warning.png" alt="Alert toast notification"></td>
<td><img src="assets/screenshot_notifications_toast_activity.png" alt="Activity toast notification"></td>
</tr></table>

Toasts only appear for notifications created since the last poll. The browser tracks the last poll time in `localStorage` (`hatchery-notif-last-read`) and compares it against each notification's `created_at` timestamp. A page load that finds no new notifications shows no toasts.

### Bell Badge

The bell icon in the top bar carries a red badge when there are active alerts. The badge count shows unread notifications; the red color signals that at least one alert is active. When there are no active alerts and no unread notifications, the badge is hidden.

![Bell icon with alert badge](assets/screenshot_notifications_bell_badge.png)

### Tray Dropdown

Clicking the bell opens a compact tray showing the five most recent notifications. Each entry shows the tier badge, a relative timestamp ("just now", "3m ago"), and the message. A "View all" link navigates to the Alerts pane.

![Notifications tray dropdown](assets/screenshot_notifications_tray.png)

### Sidebar navigation

Notifications is a nested sidebar group with two children:

```
Notifications
  ├─ Alerts   — environment alerts and activity history (`/notifications/alerts`)
  └─ Events   — per-VM provisioning event log (`/notifications/events`)
```

The parent `/notifications` route redirects to Alerts. The group expands (and the parent stays highlighted) whenever Alerts or Events is the active pane. When the sidebar is collapsed, child links appear as a flyout beside the Notifications icon (hover, keyboard focus, or click) so both destinations stay reachable without expanding the rail.

### Alerts Pane

The full notification history, accessible from the sidebar Alerts item or the tray "View all" link. Displays up to 500 notifications in reverse-chronological order. Route: `/notifications/alerts`.

Filter buttons narrow the view to a single tier (Alerts or Activity). Each row shows the time, tier badge, message, and status. Alert rows show Active or Resolved; activity rows have no status action.

![Notifications pane — full table view](assets/screenshot_notifications_pane.png)

### Events Pane

Placeholder under `/notifications/events` for the per-VM provisioning event log (see issue #114). The nav shell is in place; the live feed UI lands separately.

<br>

---

## Lifecycle

### Alerts

Alerts are written by calling `lib.notifications.record_alert(message)`. This inserts a row into the `alerts` table with:

- `created_at` — UTC ISO 8601 timestamp
- `message` — human-readable description
- `resolved = 0`, `resolved_at = NULL`

An alert is **active** while `resolved = 0`. It is **resolved** by the system (never by the user) when the condition that triggered it no longer exists. Resolution sets `resolved = 1` and `resolved_at` to the resolution timestamp.

Resolved alerts remain in the table as historical records. They appear in the Alerts pane with a "Resolved" status badge and are excluded from the active alert count used by the bell badge and footer indicator.

### Activity

Activity entries are written by calling `lib.notifications.record_activity(message)`. This inserts a row into the `activity` table with:

- `created_at` — UTC ISO 8601 timestamp
- `message` — human-readable description

Activity entries are immutable. There is no resolved or dismissed state — they are a permanent audit trail of what happened and when. The Alerts pane displays them with a `—` in the status column.

After every insert into either table, rows beyond the 500-row cap are trimmed. See [`schema/database.md`](schema/database.md) for the full schema.

### Status matrix

| Tier | State | Rendered as |
|---|---|---|
| `alert` | `resolved = 0` | Active badge |
| `alert` | `resolved = 1` | Resolved badge + timestamp |
| `activity` | _(no state)_ | — |

<br>

---

## Background Sync

Hatchery runs two sync functions at startup and then on every background cycle (controlled by the **Background Validation Interval** setting, default 60 seconds):

### Requirements sync (`_sync_requirements`)

1. Checks which required host tools are currently present via `lib.requirements.check_all()`.
2. For each missing tool, records an alert prefixed with `"Missing requirement:"` if one is not already active.
3. For each present tool, resolves any active alert with that same prefix.

### Clutch file sync (`_sync_clutches`)

1. Iterates every `.yaml` file in the clutches directory.
2. For each file, runs full schema and dependency validation via `clutch_lib.load()`.
3. On failure, records an alert prefixed with `"Invalid Clutch file: '<filename>'"` if one is not already active.
4. On success, resolves any active alert for that file.

Alerts for a deleted Clutch file are resolved immediately at delete time — not waiting for the next background cycle.

The result: alert state in the database always reflects the current environment. If a missing tool is installed or a broken Clutch file is fixed, the alert is resolved on the next sync cycle without requiring a restart.

<br>

---

## Contributor Tooling

A seed script in `.hatchery/tooling/` inserts sample notifications for UI validation and screenshot capture. Seeded records are marked with `[seed]` so they can be identified and removed without touching real notification history.

**Seed one notification at a time:**

```bash
# Insert the next curated alert (cycles through samples with each call)
uv run python .hatchery/tooling/seed_notifications.py seed alert

# Insert the next curated activity notification
uv run python .hatchery/tooling/seed_notifications.py seed activity

# Insert a custom message of any tier
uv run python .hatchery/tooling/seed_notifications.py seed alert "Missing requirement: 'virsh' is not installed"
uv run python .hatchery/tooling/seed_notifications.py seed activity "VM 'win11-dev' is hatching."
```

Calling `seed alert` or `seed activity` multiple times cycles through the curated sample list, inserting one new record per invocation. This allows incremental insertion for capturing UI state at each step — e.g., insert one, screenshot the toast; insert another, screenshot the tray; repeat.

**Seed all curated samples at once:**

```bash
uv run python .hatchery/tooling/seed_notifications.py seed all
```

Inserts all curated alert and activity samples in one pass. Useful for capturing the Notifications pane with a populated list.

**Remove all seeded records:**

```bash
uv run python .hatchery/tooling/seed_notifications.py clean
```

Deletes every record containing the `[seed]` marker from both tables. Real notifications are unaffected.

The script requires Hatchery to have been started at least once (so `hatchery.db` exists). It reads the same data directory configuration as the app, so it seeds the same database the running app reads.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Where environments hatch</div>
<br clear="both">
