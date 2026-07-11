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
  - [hatch\_sessions](#hatch_sessions)
  - [hatch\_vm\_status](#hatch_vm_status)
  - [clutch\_instances](#clutch_instances)
- [Maintenance](#maintenance)
  - [Row cap](#row-cap)
  - [Migrations](#migrations)
- [Credential storage](#credential-storage)

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

### hatch_sessions

One row per Clutch hatch initiated by the user. Groups the VMs hatched together and tracks the session lifecycle. Sessions are archived (not deleted) when they reach a terminal state.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `TEXT` | `PRIMARY KEY` | UUID v4 assigned at session creation |
| `nest` | `TEXT` | `NOT NULL DEFAULT 'local'` | Nest identifier; `'local'` for the host running Hatchery |
| `clutch_file` | `TEXT` | `NOT NULL` | Filename of the Clutch that was hatched |
| `clutch_name` | `TEXT` | `NOT NULL` | Human-readable name from the Clutch definition |
| `hatched_at` | `TEXT` | `NOT NULL` | ISO 8601 timestamp (UTC) when the session was initiated |
| `completed_at` | `TEXT` | | Set when all VMs in the session reach `fledged`; `NULL` otherwise |
| `archived_at` | `TEXT` | | Set when the session is auto-archived or manually dismissed; archived sessions are excluded from the active Nests view |

#### Managed by

`lib/hatch.py` — `create_session()`, `list_sessions()`, `archive_session()`, `archive_if_terminal()`

<br>

### hatch_vm_status

One row per VM per hatch session. Tracks the provisioning lifecycle of each VM and stores the credentials needed for post-install automation. See [Credential storage](#credential-storage).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Auto-assigned |
| `session_id` | `TEXT` | `NOT NULL REFERENCES hatch_sessions(id)` | Parent session |
| `vm_name` | `TEXT` | `NOT NULL` | VM name as known to the hypervisor; updated if renamed |
| `status` | `TEXT` | `NOT NULL DEFAULT 'pending'` | `pending` → `hatching` → `fledged` or `failed`; may transition to `culled` if the VM is removed from the host |
| `libvirt_uuid` | `TEXT` | | Hypervisor UUID assigned at creation; authoritative identity for rename and cull detection |
| `started_at` | `TEXT` | | ISO 8601 timestamp (UTC) set when status transitions to `hatching` |
| `fledged_at` | `TEXT` | | ISO 8601 timestamp (UTC) set when status transitions to `fledged` |
| `admin_username` | `TEXT` | | Admin account username configured in the answer file; stored for post-install automation and Nests inventory display |
| `admin_password` | `TEXT` | | Admin account password in plaintext; required for WinRM/SSH authentication during post-install automation — see [Credential storage](#credential-storage) |
| `error` | `TEXT` | | Error message if the VM failed to hatch; `NULL` on success |

#### Managed by

`lib/hatch.py` — `add_vm()`, `set_vm_status()`, `set_vm_uuid()`, `update_vm_name()`, `get_vm_record()`

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

## Credential storage

Admin credentials (`admin_username`, `admin_password`) are stored in `hatch_vm_status` for every VM hatched through Hatchery. **This is not optional** — post-install automation (issue [#77](https://github.com/dustinestes/Hatchery/issues/77)) requires them to authenticate over WinRM or SSH after a VM fledges in order to run provisioning scripts. Re-entering credentials at that point would break the zero-manual-steps automation goal.

### What is stored and where

Credentials are written to `hatch_vm_status` at hatch time and persist for the lifetime of the session record. They are stored as **plaintext** in the SQLite database at:

```
~/.local/share/hatchery/hatchery.db
```

The database is protected only by host filesystem permissions. It is not encrypted.

### Display in the UI

Displaying passwords in the Nests VM inventory is **opt-in** via the **Show admin passwords** setting (default: off). When off, the password column renders as `••••••••`. Usernames are always visible.

### Mitigation options

Users who want to limit credential exposure after provisioning can add a final automation script that:

- Changes the admin username and/or password after provisioning completes
- Pushes the new credentials into their own secrets management system (HashiCorp Vault, 1Password, etc.)

This is the recommended approach for environments where VMs outlive their initial setup or store sensitive data.

### Future hardening

See issue [#110](https://github.com/dustinestes/Hatchery/issues/110) for the v2 roadmap: encrypted credential storage at rest, or an authentication layer that restricts browser access to the tool.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Where environments hatch</div>
<br clear="both">
