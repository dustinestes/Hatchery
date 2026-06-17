<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Notifications</h1>
<br clear="both">

How Hatchery surfaces environment alerts and activity events — tiers, lifecycle, UI components, and startup sync.

<br>

## Contents

- [Contents](#contents)
- [Overview](#overview)
- [Tiers](#tiers)
- [UI Components](#ui-components)
  - [Toast Overlay](#toast-overlay)
  - [Bell Badge](#bell-badge)
  - [Tray Dropdown](#tray-dropdown)
  - [Notifications Pane](#notifications-pane)
- [Lifecycle](#lifecycle)
  - [Alerts](#alerts)
  - [Activity](#activity)
  - [Status matrix](#status-matrix)
- [Startup Sync](#startup-sync)
- [Contributor Tooling](#contributor-tooling)

---

<br>

## Overview

Hatchery uses a lightweight notification system to communicate two categories of events: environment alerts (missing host requirements, degraded state) and activity events (VMs hatched, Clutch files exported). Both categories are served from the same `/api/notifications` endpoint and drive the same UI surfaces.

Alerts are stored in the `alerts` table and activity in the `activity` table in `hatchery.db`. The browser polls `/api/notifications` on every page load and updates all UI surfaces — toast overlay, bell badge, tray dropdown, and the Notifications pane — without requiring a page refresh.

<br>

---

## Tiers

| Tier | Meaning | Source | Resolution |
|---|---|---|---|
| `alert` | Environment is degraded — a required tool is missing or a host condition is unmet | Startup sync | Auto-resolved when the condition clears on next restart |
| `activity` | Something happened — a VM was hatched, a Clutch was exported | User action | Immutable; no lifecycle actions |

**Alerts** are system-owned. They are recorded at startup, re-evaluated on every restart, and resolved automatically when the triggering condition is gone. An alert is active until the system resolves it — there is no user dismiss action.

**Activity** notifications are action-owned. Each user action that completes successfully (hatch, export, append) records an activity entry. These accumulate as an immutable audit trail; they have no lifecycle state and cannot be dismissed or resolved.

<br>

---

## UI Components

There are four surfaces that show notification state. All four derive from the same `/api/notifications` poll.

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

Clicking the bell opens a compact tray showing the five most recent notifications. Each entry shows the tier badge, a relative timestamp ("just now", "3m ago"), and the message. A "View all" link navigates to the full Notifications pane.

![Notifications tray dropdown](assets/screenshot_notifications_tray.png)

### Notifications Pane

The full notification history, accessible from the sidebar or the tray "View all" link. Displays up to 500 notifications in reverse-chronological order.

Filter buttons narrow the view to a single tier (Alerts or Activity). Each row shows the time, tier badge, message, and status. Alert rows show Active or Resolved; activity rows have no status action.

![Notifications pane — full table view](assets/screenshot_notifications_pane.png)

<br>

---

## Lifecycle

### Alerts

Alerts are written by calling `lib.notifications.record_alert(message)`. This inserts a row into the `alerts` table with:

- `created_at` — UTC ISO 8601 timestamp
- `message` — human-readable description
- `resolved = 0`, `resolved_at = NULL`

An alert is **active** while `resolved = 0`. It is **resolved** by the system (never by the user) when the condition that triggered it no longer exists. Resolution sets `resolved = 1` and `resolved_at` to the resolution timestamp.

Resolved alerts remain in the table as historical records. They appear in the Notifications pane with a "Resolved" status badge and are excluded from the active alert count used by the bell badge and footer indicator.

### Activity

Activity entries are written by calling `lib.notifications.record_activity(message)`. This inserts a row into the `activity` table with:

- `created_at` — UTC ISO 8601 timestamp
- `message` — human-readable description

Activity entries are immutable. There is no resolved or dismissed state — they are a permanent audit trail of what happened and when. The Notifications pane displays them with a `—` in the status column.

After every insert into either table, rows beyond the 500-row cap are trimmed. See [`schema/database.md`](schema/database.md) for the full schema.

### Status matrix

| Tier | State | Rendered as |
|---|---|---|
| `alert` | `resolved = 0` | Active badge |
| `alert` | `resolved = 1` | Resolved badge + timestamp |
| `activity` | _(no state)_ | — |

<br>

---

## Startup Sync

Every time Hatchery starts, it calls `_sync_requirements()` before serving any requests. This function:

1. Resolves all existing active alerts whose message starts with `"Missing requirement:"` — clearing any stale state from a previous run.
2. Checks which required host tools are currently missing via `lib.requirements.check_all()`.
3. Records a fresh `alert` for each missing tool.

The result: the alert state in the database always reflects the current host condition as of the last startup. If a tool was missing in a prior run and is now installed, the old alert is resolved and no new one is recorded. If a new tool is missing, a fresh alert appears.

Requirements are not re-checked on every request — only at startup. Restarting Hatchery after installing missing tools clears the alerts.

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
