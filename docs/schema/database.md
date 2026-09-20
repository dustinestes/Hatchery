<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Database Schema Reference</h1>
<br clear="both">

Table definitions, column types, and maintenance details for `hatchery.db`.

<br>

## Contents

- [Contents](#contents)
- [Tables](#tables)
  - [alerts](#alerts)
  - [app\_settings](#app_settings)
  - [nests](#nests)
  - [hatch\_sessions](#hatch_sessions)
  - [hatch\_vm\_status](#hatch_vm_status)
  - [hatch\_vm\_scripts](#hatch_vm_scripts)
  - [hatch\_events](#hatch_events)
  - [clutch\_instances](#clutch_instances)
  - [validator\_runs](#validator_runs)
  - [library\_cache\_provenance](#library_cache_provenance)
- [Maintenance](#maintenance)
  - [Hatch session archive purge](#hatch-session-archive-purge)
  - [Migrations](#migrations)
- [Credential storage](#credential-storage)

---

<br>

## Tables

### alerts

Stores active and resolved environment alerts. An alert is created when a host condition is degraded (e.g. a required tool is missing) and resolved automatically when the condition clears. Consumed by the alerts tray, toast overlay, bell badge, and Alerts pane.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Auto-assigned |
| `created_at` | `TEXT` | `NOT NULL` | ISO 8601 timestamp (UTC) |
| `message` | `TEXT` | `NOT NULL` | Human-readable description of the condition |
| `tier` | `TEXT` | `NOT NULL DEFAULT 'alert'` | Same vocabulary as UI toasts: `info`, `warning`, or `alert` |
| `resolved` | `INTEGER` | `NOT NULL DEFAULT 0` | `0` = active, `1` = resolved |
| `resolved_at` | `TEXT` | | ISO 8601 timestamp (UTC) set when `resolved` transitions to `1`; `NULL` while active |

#### Managed by

`lib/alerts.py` — `record_alert()`, `resolve()`, `resolve_alerts_by_prefix()`, `has_active_alert()`, `count_active_alerts()`, `list_recent()`

<br>

### validator_runs

History of pluggable validator executions (Notifications → Validators). Separate from **alerts** (findings). See [validators.md](../validators.md).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Auto-assigned |
| `validator_id` | `TEXT` | `NOT NULL` | Registry id (e.g. `clutch_files`) |
| `started_at` | `TEXT` | `NOT NULL` | ISO 8601 UTC |
| `finished_at` | `TEXT` | | ISO 8601 UTC when complete |
| `status` | `TEXT` | `NOT NULL` | `ok`, `findings`, or `error` (execution outcome — [#280](https://github.com/dustinestes/Hatchery/issues/280)) |
| `tier` | `TEXT` | `NOT NULL DEFAULT 'info'` | `info` / `warning` / `alert` |
| `trigger` | `TEXT` | `NOT NULL` | `schedule`, `manual`, or `connection` |
| `message` | `TEXT` | `NOT NULL` | Short summary |
| `detail` | `TEXT` | | Optional error detail |
| `nest_id` | `TEXT` | | Optional Nest scope |
| `findings_count` | `INTEGER` | `NOT NULL DEFAULT 0` | Optional findings signal |

#### Managed by

`lib/validators/runs.py` — `record_run()`, `list_runs()`, `latest_by_validator()`

<br>

### library_cache_provenance

Attribution of operator-cache files pulled via Library ([#308](https://github.com/dustinestes/Hatchery/issues/308)). Architecture: [ADR-0012](../adr/0012-library-cache-provenance-drift.md).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Auto-assigned |
| `domain` | `TEXT` | `NOT NULL` | `scripts`, `clutches`, or `media` |
| `media_target` | `TEXT` | `NOT NULL DEFAULT ''` | `iso` / `virtio` for media; empty otherwise |
| `cache_name` | `TEXT` | `NOT NULL` | Basename in operator cache |
| `connection_id` | `TEXT` | `NOT NULL` | Stable Library connection id |
| `binding_id` | `TEXT` | | Optional binding id |
| `relative_path` | `TEXT` | `NOT NULL` | Path on the source |
| `source_type` | `TEXT` | `NOT NULL` | Connection type at pull (`path`, `forge`, …) |
| `cache_sha256` | `TEXT` | `NOT NULL` | Observed Hatchery SHA-256 of cache bytes (each evaluate) |
| `cache_sha256_synced` | `TEXT` | `NOT NULL` | Cache SHA at last successful sync/pull |
| `source_digest` | `TEXT` | | Observed remote tip (each evaluate) |
| `source_digest_synced` | `TEXT` | | Remote tip at last successful sync/pull |
| `source_digest_kind` | `TEXT` | | `sha256`, `git_blob`, or `size_mtime` |
| `drift_state` | `TEXT` | `NOT NULL DEFAULT 'unknown'` | `in_sync`, `out_of_sync`, `unknown`, `orphan` |
| `checked_at` | `TEXT` | | Last evaluate |
| `pulled_at` | `TEXT` | `NOT NULL` | Last successful sync/pull |
| `updated_at` | `TEXT` | `NOT NULL` | Row update time |
| | | `UNIQUE(domain, media_target, cache_name)` | One row per cached basename |

#### Managed by

`lib/library_provenance.py` — `upsert_on_pull()`, `apply_evaluate_result()`, `reattach()`, …

<br>

### app_settings

Key/value store for operational Settings (JSON-encoded values). The external bootstrap YAML keeps only `data_dir` — see [Settings storage](../settings.md).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `key` | `TEXT` | `PRIMARY KEY` | Setting name (e.g. `bg_interval`, `show_passwords`) |
| `value` | `TEXT` | `NOT NULL` | JSON text (number, bool, string, array, or object) |

#### Managed by

`lib/config.py` — `bind_db()`, `save()`

<br>

### nests

Registered Nest connections (where VMs live). Fresh databases start with an **empty** registry ([ADR-0014](../adr/0014-optional-local-nest.md) / [#266](https://github.com/dustinestes/Hatchery/issues/266)). Local Nest id `local` is optional (session `--nest-local`, Settings Add Local Nest, or an existing migrated row). Remote Nests store endpoint and credential **references** — not private key bytes or long-lived WinRM passwords (those wait on [#110](https://github.com/dustinestes/Hatchery/issues/110)).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `TEXT` | `PRIMARY KEY` | Stable Nest id (e.g. `local`); referenced by `hatch_sessions.nest` |
| `name` | `TEXT` | `NOT NULL` | Display label in Settings and the Nests pane |
| `provider_type` | `TEXT` | `NOT NULL` | `libvirt`, `utm`, or `hyperv` (routed by [`lib/providers/factory.py`](../../lib/providers/factory.py); only local libvirt is instantiable today) |
| `location` | `TEXT` | `NOT NULL DEFAULT 'local'` | `local` or `remote` |
| `transport` | `TEXT` | | `ssh` or `winrm` when remote; `NULL` when local |
| `host` | `TEXT` | | Remote hostname or IP |
| `port` | `INTEGER` | | SSH/WinRM port |
| `ssh_user` | `TEXT` | | Optional SSH username |
| `identity_file` | `TEXT` | | Path to OpenSSH private key **on the Hatchery host** (never key bytes) |
| `cert_path` | `TEXT` | | Optional OpenSSH certificate path for Valid-before expiry |
| `identity_expires_at` | `TEXT` | | Optional operator policy expiry (ISO 8601); plain keys have no in-file expiry |
| `known_hosts` | `TEXT` | | `default`, `accept-new`, or `skip` |
| `winrm_user` | `TEXT` | | WinRM username when transport is `winrm` |
| `credential_ref` | `TEXT` | | Placeholder for secrets store (#110) — not a password |
| `extra_json` | `TEXT` | | Optional JSON object |
| `created_at` | `TEXT` | `NOT NULL` | ISO 8601 UTC |
| `updated_at` | `TEXT` | `NOT NULL` | ISO 8601 UTC |

#### Managed by

`lib/nests.py` — `list_nests()`, `get_nest()`, `replace_nests()`, `ensure_local_nest()` (opt-in `--nest-local`), `default_nest_id()`, `test_connection()`, `identities_for_expiry()`

<br>

### hatch_sessions

One row per Clutch hatch initiated by the user. Groups the VMs hatched together and tracks the session lifecycle. Sessions are archived (not deleted) when they reach a terminal state.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `TEXT` | `PRIMARY KEY` | UUID v4 assigned at session creation |
| `nest` | `TEXT` | `NOT NULL DEFAULT 'local'` | Nest registry id (see [nests](#nests)); `'local'` for the built-in host Nest |
| `clutch_file` | `TEXT` | `NOT NULL` | Filename of the Clutch that was hatched |
| `clutch_name` | `TEXT` | `NOT NULL` | Human-readable name from the Clutch definition |
| `hatched_at` | `TEXT` | `NOT NULL` | ISO 8601 timestamp (UTC) when the session was initiated |
| `completed_at` | `TEXT` | | Set when all VMs in the session reach `fledged`; `NULL` otherwise |
| `archived_at` | `TEXT` | | Set when the session is auto-archived or manually dismissed; archived sessions are excluded from the active Nests view. Archiving also deletes child rows (`hatch_events`, `hatch_vm_scripts`, `hatch_vm_status`) for the session |

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

### hatch_vm_scripts

One row per automation script per VM per session. Records the declared scripts at hatch time (before any run) and is updated as each script executes. This allows the Nests panel to display the full script queue immediately after hatching, before provisioning begins.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Auto-assigned |
| `session_id` | `TEXT` | `NOT NULL REFERENCES hatch_sessions(id)` | Parent session |
| `vm_name` | `TEXT` | `NOT NULL` | VM name; kept in sync with `hatch_vm_status.vm_name` |
| `script_name` | `TEXT` | `NOT NULL` | Filename of the script in `automation/scripts/` |
| `run_order` | `INTEGER` | `NOT NULL` | Zero-based execution order within this VM's script list |
| `reboot_after` | `INTEGER` | `NOT NULL DEFAULT 0` | `1` if Hatchery should reboot the VM after this script succeeds |
| `status` | `TEXT` | `NOT NULL DEFAULT 'pending'` | `pending` → `running` → `succeeded` or `failed`; `skipped` if a prior script failed |
| `exit_code` | `INTEGER` | | Exit code returned by the script; `NULL` until the script completes |
| `output` | `TEXT` | | Combined stdout + stderr from the script run; `NULL` until complete |
| `parameters` | `TEXT` | | JSON-encoded map of named parameter values passed to this script; `NULL` if no parameters |
| `started_at` | `TEXT` | | ISO 8601 timestamp (UTC) set when status transitions to `running` |
| `completed_at` | `TEXT` | | ISO 8601 timestamp (UTC) set when status transitions to `succeeded`, `failed`, or `skipped` |

#### Constraints

`UNIQUE(session_id, vm_name, run_order)` — each (session, VM, position) is unique; enforces that scripts are not double-inserted.

#### Managed by

`lib/hatch.py` — `add_vm_scripts()`, `get_vm_scripts()`, `set_script_status()`, `reset_scripts_for_retry()`

<br>

### hatch_events

One row per provisioning event emitted during a VM's hatch lifecycle. Events come from two sources: Hatchery itself (lifecycle milestones such as script start/complete, reboots, fledged) and automation scripts (lines emitted via `Write-HatchEvent`). Together they form the per-VM event log displayed in the Events pane under Notifications.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Auto-assigned; defines insertion order |
| `session_id` | `TEXT` | `NOT NULL REFERENCES hatch_sessions(id)` | Parent session |
| `vm_name` | `TEXT` | `NOT NULL` | VM this event belongs to |
| `context` | `TEXT` | `NOT NULL` | `'hatchery'` for host-side lifecycle events; `'script'` for `Write-HatchEvent` lines |
| `level` | `TEXT` | `NOT NULL` | `'INFO'`, `'WARN'`, or `'ERROR'` — controls styling in the UI |
| `script_name` | `TEXT` | | Script file that generated this event; `NULL` for session-level hatchery events |
| `component` | `TEXT` | | Optional sub-label from `Write-HatchEvent -Component`; `NULL` for hatchery events and script events without a component |
| `message` | `TEXT` | `NOT NULL` | Human-readable event text |
| `received_at` | `TEXT` | `NOT NULL` | ISO 8601 timestamp (UTC) recorded by Hatchery when the event was stored — not the guest's clock |

#### Context and component

`context` identifies *who* generated the event: `'hatchery'` means Hatchery emitted it directly (e.g. "Starting script: setup.ps1"); `'script'` means it came from a `Write-HatchEvent` call inside an automation script.

`component` is an optional grouping label within a script, set by the `-Component` parameter of `Write-HatchEvent` (e.g. `"Chocolatey"`, `"Registry"`). It is always `NULL` for hatchery-context events.

#### Managed by

`lib/hatch.py` — `add_event()`, `get_events()`, `parse_hatch_event_lines()`

`GET /api/sessions/<session_id>/vms/<vm_name>/events` — returns all events for a VM in insertion order.

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

Hatchery does **not** auto-delete historical rows by age, count, or FIFO. Records stay until they are **no longer applicable**. Further capacity management (including any DB file-size alert) is the operator's concern — see [#169](https://github.com/dustinestes/Hatchery/issues/169).

### Hatch session archive purge

When a hatch session is archived (manual dismiss or `archive_if_terminal`), its environment is no longer tracked, so Hatchery deletes that session's child rows in the same transaction:

| Table | Action |
|---|---|
| `hatch_events` | `DELETE` for `session_id` |
| `hatch_vm_scripts` | `DELETE` for `session_id` |
| `hatch_vm_status` | `DELETE` for `session_id` |
| `hatch_sessions` | Kept; `archived_at` set |

Active sessions keep a complete event transcript until archive. Alert rows are never auto-trimmed; resolved alerts remain as history.

Implemented in `lib/hatch.py` — `_purge_session_children()`, called from `archive_session()` and `archive_if_terminal()`.

### Migrations

Schema creation uses `CREATE TABLE IF NOT EXISTS` on startup. Additive column changes for existing local DBs are applied in `lib/db._migrate` (for example adding `alerts.tier`). There is no versioned migration list yet — delete `hatchery.db` (or use a fresh data dir) only if a local DB is too old for a simple `ALTER TABLE` to repair.

When a real migration framework becomes necessary:

1. Add a `schema_version` table to track applied migrations
2. Apply `ALTER TABLE` statements on startup when the version is behind
3. Bump the version after each migration

<br>

---

## Credential storage

Admin credentials (`admin_username`, `admin_password`) are stored in `hatch_vm_status` for every VM hatched through Hatchery. **This is not optional** — post-install automation (issue [#77](https://github.com/dustinestes/Hatchery/issues/77)) requires them to authenticate over WinRM or SSH after a VM fledges in order to run provisioning scripts. Re-entering credentials at that point would break the zero-manual-steps automation goal.

### What is stored and where

Credentials are written to `hatch_vm_status` at hatch time and persist until the session is archived (child rows, including credentials, are purged on archive). They are stored as **plaintext** in the SQLite database at:

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
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
