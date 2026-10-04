<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Events</h1>
<br clear="both">

Per-VM event log written throughout the hatching and provisioning lifecycle - what gets recorded, when, and why.

<br>

## Contents

- [Contents](#contents)
- [Overview](#overview)
- [Event Schema](#event-schema)
- [Contexts](#contexts)
- [Levels](#levels)
- [Lifecycle Events (hatchery context)](#lifecycle-events-hatchery-context)
  - [Session Initiation](#session-initiation)
  - [VM Creation](#vm-creation)
  - [Windows Setup](#windows-setup)
  - [Provisioning](#provisioning)
  - [Retry](#retry)
- [Script Events (script context)](#script-events-script-context)
- [API](#api)
- [Retention](#retention)

---

<br>

## Overview

Every VM in a hatch session has its own event log stored in the `hatch_events` table. Events are written by two sources:

- **Hatchery** - host-side lifecycle events emitted as each stage of the hatch progresses (VM creation, Windows setup detection, script execution, reboots, errors). These use context `'hatchery'`.
- **Scripts** - structured log lines emitted by `Write-HatchEvent` inside automation scripts, parsed from script output after each script completes. These use context `'script'`.

Events are ordered by insertion and scoped to `(session_id, vm_name)`. They are displayed in the **Events** pane under Notifications in the sidebar (`/notifications/events`).

<br>

---

<br>

## Event Schema

Each event row in `hatch_events` has these columns:

| Column | Type | Description |
|---|---|---|
| `id` | integer | Auto-incrementing primary key; also determines insertion order |
| `session_id` | text | References `hatch_sessions.id` - the clutch hatch this event belongs to |
| `vm_name` | text | Name of the VM this event was recorded for |
| `context` | text | `'hatchery'` or `'script'` - who emitted this event |
| `level` | text | `'INFO'`, `'WARN'`, or `'ERROR'` |
| `script_name` | text \| null | Script file name (`.ps1`) when the event is tied to a specific script; null for session-level events |
| `component` | text \| null | Optional sub-label from `Write-HatchEvent -Component`; always null for `'hatchery'` context events |
| `message` | text | The event message |
| `received_at` | text | UTC ISO 8601 timestamp. For host-side events this is the time Hatchery wrote the record. For events imported from a guest log file (e.g. `hatchery-setup-windows.log`), this is the guest-side timestamp embedded in the log line - preserving the time each step actually ran. |

<br>

---

<br>

## Contexts

| Context | Emitted by | When |
|---|---|---|
| `hatchery` | Hatchery (Python) | Host-side lifecycle stages - VM creation, setup detection, provisioning control flow, errors |
| `script` | `Write-HatchEvent` (PowerShell) | Lines emitted by automation scripts, parsed from script output after each script completes |

<br>

---

<br>

## Levels

| Level | Meaning |
|---|---|
| `INFO` | Normal progress - stage started, stage completed, values observed |
| `WARN` | Non-fatal advisory - fallback taken, optional step skipped |
| `ERROR` | Failure - VM creation failed, script failed, WinRM connection lost |

<br>

---

<br>

## Lifecycle Events (hatchery context)

All events in this section use `context = 'hatchery'`. The `component` column is always null for these events.

### Session Initiation

Emitted in `hatch_clutch_post` when a clutch hatch is submitted from the UI, before the background thread starts. One event is written per VM.

| Level | Message pattern | `script_name` | When |
|---|---|---|---|
| `INFO` | `Hatching clutch: <name>` | null | Clutch hatch submitted; session and VM records created |

---

### VM Creation

Emitted in `lib.hatch_lifecycle.run_hatch_session` (background thread). The "Creating VM" event includes the full `virt-install` command so you can see exactly what Hatchery passed to libvirt.

| Level | Message pattern | `script_name` | When |
|---|---|---|---|
| `INFO` | `Creating VM: virt-install --name <name> ...` | null | Before `virt-install` is invoked |
| `INFO` | `VM created successfully` | null | `virt-install` returned exit code 0 |
| `ERROR` | `VM creation failed: <reason>` | null | `virt-install` raised an exception |

The "Creating VM" message contains the complete command as it will be run, including memory, vCPU, disk size, OS variant, ISO path, UEFI/TPM flags, and VirtIO cdrom if configured. The floppy image path (answer file) is not included because it is created dynamically after this event is written.

---

### Windows Setup

Emitted in `lib.hatch_lifecycle.sync_hatch_status` (Hatch status poller, runs every `bg_interval` seconds). These events track the Windows unattended install phase after `virt-install` returns.

| Level | Message pattern | `script_name` | When |
|---|---|---|---|
| `INFO` | `Starting VM: virsh start <name>` | null | VM found shut off during hatching phase - Windows OOBE triggered ACPI power-off; Hatchery restarts it |
| `INFO` | `Windows setup complete - starting provisioning (<n> scripts)` | null | `hatchery-ready` flag detected on guest, scripts are queued |
| `INFO` | `Windows setup complete - no automation scripts configured` | null | `hatchery-ready` flag detected, no scripts declared for this VM |

The `hatchery-ready` flag is a file written by the last `FirstLogonCommand` in every answer file template. Hatchery polls for it (via WinRM) to ensure all first-boot setup finishes before automation scripts begin. It is deleted immediately on detection.

The "Starting VM" event may appear multiple times during a long Windows install - OOBE issues several ACPI power-off signals at different stages (driver installation, region selection, user account creation). Each one triggers a restart and a new event.

---

### Provisioning

Emitted in `_provision_vm_thread` (per-VM background thread). Events are written before and after each automation script, and around reboot points.

| Level | Message pattern | `script_name` | When |
|---|---|---|---|
| `INFO` | `Starting script: <name>.ps1` | `<name>.ps1` | Before the script is sent to the guest over WinRM |
| `INFO` | `Script complete: <name>.ps1 - Exit Code: 0` | `<name>.ps1` | Script returned exit code 0 |
| `ERROR` | `Script failed: <name>.ps1 - Exit Code: <n>` | `<name>.ps1` | Script returned a non-zero exit code |
| `ERROR` | `Script failed: WinRM connection error - <detail>` | `<name>.ps1` | WinRM connection raised an exception before or during script execution |
| `INFO` | `Rebooting VM after script: <name>.ps1` | `<name>.ps1` | Script has `reboot_after: true`; guest restart initiated |
| `INFO` | `Guest reboot confirmed: <UTC ISO> (LastBootUpTime=<FILETIME>)` | `<name>.ps1` | Guest boot time changed after `reboot_after`; ISO matches event log timestamps ([#499](https://github.com/dustinestes/Hatchery/issues/499)) |
| `INFO` | `Waiting for WinRM to stabilize after reboot (N consecutive probes)` | `<name>.ps1` | Post-reboot settle before the next automation |
| `INFO` | `WinRM stable after reboot (N consecutive probes)` | `<name>.ps1` | Settle complete; safe to continue |
| `WARN` | `WinRM probe failed during settle - resetting stability count…` | `<name>.ps1` | Transient remoting flake during settle |
| `INFO` | `Raised guest WinRM MaxEnvelopeSizekb for Software staging (…)` | Software id | Guest envelope raised before payload Send |
| `INFO` | `Running detect (pre-install)` | Software id | Pre-stage detect; present skips transfer/install |
| `INFO` | `Software already present - skipping stage/install` | Software id | Pre-install detect present; step succeeds without staging |
| `INFO` | `Running install: {os}.{arch}.install.command` | Software id | Resolved ``software.yaml`` unit path (not the command body) |
| `INFO` | `Install finished with exit N` | Software id | Install command completed (authored ``software.yaml`` exit) |
| `INFO` | `Running detect (verify install)` | Software id | Post-install detect; fail step if missing |
| `INFO` | `WinRM upload of <file> succeeded on attempt i/n` | Software id | Staging recovered after a transient fault |
| `INFO` | `All scripts succeeded - VM is fledged` | null | All scripts completed successfully; VM status set to `fledged` |

When a script fails (non-zero exit code or WinRM error), all remaining scripts in the queue are marked `skipped` and provisioning halts. The VM is set to `failed` state and can be retried from the Nests panel.

---

### Retry

Emitted in `api_retry_vm` when a failed VM is retried from the Nests panel.

| Level | Message pattern | `script_name` | When |
|---|---|---|---|
| `INFO` | `Retry initiated` | null | Retry request received; failed/skipped scripts reset to pending |

<br>

---

<br>

## Script Events (script context)

Script events come from two sources, both using context `'script'`:

**Automation scripts** - `Write-HatchEvent` lines emitted inside user-authored `.ps1` scripts. Parsed from captured output after each script completes and inserted in order.

**First-boot setup** - structured log lines written by `hatchery-setup-windows.ps1` to `C:\Program Files\Hatchery\logs\hatchery-setup-windows.log` during the Windows first-boot phase, before Guest transport is available. Hatchery imports this file immediately after WinRM connects (issue #133), then deletes it. Because these events come from a log file rather than live output, each line carries a guest-side UTC timestamp that is used directly as `received_at` - so step durations are preserved as they happened on the guest, not at import time.

| Context | Level | `script_name` | `component` | Source |
|---|---|---|---|---|
| `script` | `INFO` | `<name>.ps1` | value or null | `Write-HatchEvent "message"` in automation script |
| `script` | `WARN` | `<name>.ps1` | value or null | `Write-HatchEvent "message" -Level WARN` |
| `script` | `ERROR` | `<name>.ps1` | value or null | `Write-HatchEvent "message" -Level ERROR` |
| `script` | `INFO` | `hatchery-setup-windows.ps1` | `setup` or `step-N` | Setup step started / succeeded (imported from log file) |
| `script` | `ERROR` | `hatchery-setup-windows.ps1` | `step-N` | Setup step failed (imported from log file) |

The `component` column is populated from `-Component "label"` in `Write-HatchEvent`, or from the step label (`setup`, `step-1` … `step-9`) in the setup log. It is null when omitted.

Script events appear in the log interleaved with hatchery events, ordered by `id` (insertion order). Automation script events are inserted as a batch after each script completes (pywinrm is blocking). Setup log events are imported as a batch when WinRM first connects.

See [automations.md](automations.md#write-hatchevent) for `Write-HatchEvent` usage and the wire format.

<br>

---

<br>

## API

Global Events console (#527):

```
GET /api/events?limit=50&offset=0&scope=active&vm=&session_id=&level=&q=
```

Returns newest-first pages: `{ "events": [...], "total", "limit", "offset" }`.
Each row includes `session_id`, `vm_name`, and `clutch_name`. `scope=active`
limits to non-archived sessions; `scope=all` includes archived session rows
that still remain (archived sessions normally delete child events on archive).

Per-VM transcript (sticky VM detail / automation):

```
GET /api/sessions/<session_id>/vms/<vm_name>/events
```

Returns a JSON object with an `events` array in insertion order:

```json
{
  "events": [
    {
      "id": 1,
      "context": "hatchery",
      "level": "INFO",
      "script_name": null,
      "component": null,
      "message": "Hatching clutch: my-lab",
      "received_at": "2026-07-15T18:00:00+00:00"
    },
    {
      "id": 2,
      "context": "hatchery",
      "level": "INFO",
      "script_name": null,
      "component": null,
      "message": "Creating VM: virt-install --name dc01 --memory 4096 ...",
      "received_at": "2026-07-15T18:00:01+00:00"
    },
    {
      "id": 5,
      "context": "script",
      "level": "INFO",
      "script_name": "configure-vm-basics.ps1",
      "component": null,
      "message": "Setting timezone to Central Standard Time",
      "received_at": "2026-07-15T18:12:44+00:00"
    }
  ]
}
```

The **Events** pane (`/notifications/events`) is a flat paginated console over
`GET /api/events` (search, VM, session, level, active/all). VM-scoped filtering
lives on the sticky VM detail page (`GET /api/sessions/.../events`). Timestamps
use `resolved_timezone` from `/api/config`. The transcript remains viewable after
a VM reaches `fledged` or `failed` for as long as the hatch session is active
(not archived).

`received_at` is always stored in UTC. **Settings → Display** lets you choose whether timestamps are shown in UTC or host local time - conversion happens in the UI using the `resolved_timezone` value from `/api/config`.

<br>

---

<br>

## Retention

Event rows are kept for the life of the **active** hatch session so the transcript stays complete while the environment is still tracked. When the session is archived (dismissed from Nests, or auto-archived after a terminal/degraded state), Hatchery deletes that session's `hatch_events` along with related `hatch_vm_scripts` and `hatch_vm_status` rows. The `hatch_sessions` row remains with `archived_at` set.

Hatchery does not trim event rows by age or count while a session is active - a partial transcript is not useful. Space is reclaimed only when the session is archived (no longer applicable). Broader DB capacity is the operator's concern; a future file-size alert is tracked in [#169](https://github.com/dustinestes/Hatchery/issues/169).

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
