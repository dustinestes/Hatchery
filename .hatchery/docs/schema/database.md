<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Database Schema Reference</h1>
<br clear="both">

Table definitions, column types, and maintenance details for `hatchery.db`.

<br>

## Contents

- [Contents](#contents)
- [Tables](#tables)
  - [alerts](#alerts)
  - [activity](#activity)
  - [clutch\_instances](#clutch_instances)
- [Maintenance](#maintenance)
  - [Row cap](#row-cap)
  - [Migrations](#migrations)

---

<br>

## Tables

### alerts

Stores active and resolved environment alerts. An alert is created when a host condition is degraded (e.g. a required tool is missing) and resolved automatically when the condition clears. Consumed by the notification tray, toast overlay, bell badge, and Notifications pane.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Auto-assigned |
| `created_at` | `TEXT` | `NOT NULL` | ISO 8601 timestamp (UTC) |
| `message` | `TEXT` | `NOT NULL` | Human-readable description of the condition |
| `resolved` | `INTEGER` | `NOT NULL DEFAULT 0` | `0` = active, `1` = resolved |
| `resolved_at` | `TEXT` | | ISO 8601 timestamp (UTC) set when `resolved` transitions to `1`; `NULL` while active |

#### Managed by

`lib/notifications.py` — `record_alert()`, `resolve()`, `resolve_alerts_by_prefix()`, `has_active_alert()`, `count_active_alerts()`

<br>

### activity

Immutable audit trail of user actions and provisioning events (e.g. "VM hatching started", "Clutch exported"). Entries are never updated or deleted except by the row-cap trim. Consumed by the notification tray, toast overlay, and Notifications pane.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Auto-assigned |
| `created_at` | `TEXT` | `NOT NULL` | ISO 8601 timestamp (UTC) |
| `message` | `TEXT` | `NOT NULL` | Human-readable description of the event |

#### Managed by

`lib/notifications.py` — `record_activity()`

<br>

### clutch_instances

Tracks observed runtime state of VMs hatched from Clutch definitions. Associates each running VM with the Clutch that defined it, enabling instance-aware reconciliation.

> **Stub** — additional columns are defined in issue [#19](https://github.com/dustinestes/Hatchery/issues/19). The table is created in this schema so the database structure is in place before the feature is implemented.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Auto-assigned |
| _(additional columns)_ | — | — | Defined in #19 |

<br>

---

## Maintenance

### Row cap

Both `alerts` and `activity` are independently capped at **500 rows**. On every insert, the corresponding trim function deletes the oldest rows beyond the cap. This runs automatically — no manual maintenance required.

| Table | Cap | Trim function |
|---|---|---|
| `alerts` | 500 | `lib/db.trim_alerts()` |
| `activity` | 500 | `lib/db.trim_activity()` |

The caps are defined as `_MAX_ALERTS = 500` and `_MAX_ACTIVITY = 500` in `lib/db.py`.

### Migrations

The current schema uses `CREATE TABLE IF NOT EXISTS`, which is idempotent and safe to run on every startup. It cannot alter existing tables.

When a future change requires adding or modifying columns, the approach will be:

1. Add a `schema_version` table to track applied migrations
2. Apply `ALTER TABLE` statements on startup when the version is behind
3. Bump the version after each migration

No migration infrastructure is needed yet. This is the documented plan for when it becomes necessary.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Where environments hatch</div>
<br clear="both">
