<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Events</h1>
<br clear="both">

Per-VM event log written throughout the hatching and provisioning lifecycle — what gets recorded, when, and why.

<br>

## Contents

- [Contents](#contents)
- [Overview](#overview)
- [Event Schema](#event-schema)
- [Contexts](#contexts)
- [Tiers](#tiers)
- [Lifecycle Events (hatchery context)](#lifecycle-events-hatchery-context)
  - [Session Initiation](#session-initiation)
  - [VM Creation](#vm-creation)
  - [Windows Setup](#windows-setup)
  - [Provisioning](#provisioning)
  - [Retry](#retry)
- [Script Events (script context)](#script-events-script-context)
- [API](#api)

---

<br>

## Overview

Every VM in a hatch session has its own event log stored in the `hatch_events` table. Events are written by two sources:

- **Hatchery** — host-side lifecycle events emitted as each stage of the hatch progresses (VM creation, Windows setup detection, script execution, reboots, errors). These use context `'hatchery'`.
- **Scripts** — structured log lines emitted by `Write-HatchEvent` inside automation scripts, parsed from script output after each script completes. These use context `'script'`.

Events are ordered by insertion and scoped to `(session_id, vm_name)`. The future Events panel in the Nests pane will display these in a unified chronological view.

<br>

---

<br>

## Event Schema

Each event row in `hatch_events` has these columns:

| Column | Type | Description |
|---|---|---|
| `id` | integer | Auto-incrementing primary key; also determines insertion order |
| `session_id` | text | References `hatch_sessions.id` — the clutch hatch this event belongs to |
| `vm_name` | text | Name of the VM this event was recorded for |
| `context` | text | `'hatchery'` or `'script'` — who emitted this event |
| `tier` | text | `'INFO'`, `'WARN'`, or `'ERROR'` |
| `script_name` | text \| null | Script file name (`.ps1`) when the event is tied to a specific script; null for session-level events |
| `component` | text \| null | Optional sub-label from `Write-HatchEvent -Component`; always null for `'hatchery'` context events |
| `message` | text | The event message |
| `received_at` | text | UTC ISO 8601 timestamp of when Hatchery recorded the event |

<br>

---

<br>

## Contexts

| Context | Emitted by | When |
|---|---|---|
| `hatchery` | Hatchery (Python) | Host-side lifecycle stages — VM creation, setup detection, provisioning control flow, errors |
| `script` | `Write-HatchEvent` (PowerShell) | Lines emitted by automation scripts, parsed from script output after each script completes |

<br>

---

<br>

## Tiers

| Tier | Meaning |
|---|---|
| `INFO` | Normal progress — stage started, stage completed, values observed |
| `WARN` | Non-fatal advisory — fallback taken, optional step skipped |
| `ERROR` | Failure — VM creation failed, script failed, WinRM connection lost |

<br>

---

<br>

## Lifecycle Events (hatchery context)

All events in this section use `context = 'hatchery'`. The `component` column is always null for these events.

### Session Initiation

Emitted in `hatch_clutch_post` when a clutch hatch is submitted from the UI, before the background thread starts. One event is written per VM.

| Tier | Message pattern | `script_name` | When |
|---|---|---|---|
| `INFO` | `Hatching clutch: <name>` | null | Clutch hatch submitted; session and VM records created |

---

### VM Creation

Emitted in `_run_hatch_session` (background thread). The "Creating VM" event includes the full `virt-install` command so you can see exactly what Hatchery passed to libvirt.

| Tier | Message pattern | `script_name` | When |
|---|---|---|---|
| `INFO` | `Creating VM: virt-install --name <name> ...` | null | Before `virt-install` is invoked |
| `INFO` | `VM created successfully` | null | `virt-install` returned exit code 0 |
| `ERROR` | `VM creation failed: <reason>` | null | `virt-install` raised an exception |

The "Creating VM" message contains the complete command as it will be run, including memory, vCPU, disk size, OS variant, ISO path, UEFI/TPM flags, and VirtIO cdrom if configured. The floppy image path (answer file) is not included because it is created dynamically after this event is written.

---

### Windows Setup

Emitted in `_sync_hatch_status` (background sync loop, runs every `bg_interval` seconds). These events track the Windows unattended install phase after `virt-install` returns.

| Tier | Message pattern | `script_name` | When |
|---|---|---|---|
| `INFO` | `Starting VM: virsh start <name>` | null | VM found shut off during hatching phase — Windows OOBE triggered ACPI power-off; Hatchery restarts it |
| `INFO` | `Windows setup complete — starting provisioning (<n> scripts)` | null | `hatchery-ready` flag detected on guest, scripts are queued |
| `INFO` | `Windows setup complete — no automation scripts configured` | null | `hatchery-ready` flag detected, no scripts declared for this VM |

The `hatchery-ready` flag is a file written by the last `FirstLogonCommand` in every answer file template. Hatchery polls for it (via WinRM) to ensure all first-boot setup finishes before automation scripts begin. It is deleted immediately on detection.

The "Starting VM" event may appear multiple times during a long Windows install — OOBE issues several ACPI power-off signals at different stages (driver installation, region selection, user account creation). Each one triggers a restart and a new event.

---

### Provisioning

Emitted in `_provision_vm_thread` (per-VM background thread). Events are written before and after each automation script, and around reboot points.

| Tier | Message pattern | `script_name` | When |
|---|---|---|---|
| `INFO` | `Starting script: <name>.ps1` | `<name>.ps1` | Before the script is sent to the guest over WinRM |
| `INFO` | `Script complete: <name>.ps1 — Exit Code: 0` | `<name>.ps1` | Script returned exit code 0 |
| `ERROR` | `Script failed: <name>.ps1 — Exit Code: <n>` | `<name>.ps1` | Script returned a non-zero exit code |
| `ERROR` | `Script failed: WinRM connection error — <detail>` | `<name>.ps1` | WinRM connection raised an exception before or during script execution |
| `INFO` | `Rebooting VM after script: <name>.ps1` | `<name>.ps1` | Script has `reboot_after: true`; guest restart initiated |
| `INFO` | `WinRM reconnected after reboot` | `<name>.ps1` | WinRM connection re-established after the `reboot_after` restart |
| `INFO` | `All scripts succeeded — VM is fledged` | null | All scripts completed successfully; VM status set to `fledged` |

When a script fails (non-zero exit code or WinRM error), all remaining scripts in the queue are marked `skipped` and provisioning halts. The VM is set to `failed` state and can be retried from the Nests panel.

---

### Retry

Emitted in `api_retry_vm` when a failed VM is retried from the Nests panel.

| Tier | Message pattern | `script_name` | When |
|---|---|---|---|
| `INFO` | `Retry initiated` | null | Retry request received; failed/skipped scripts reset to pending |

<br>

---

<br>

## Script Events (script context)

Script events are emitted by `Write-HatchEvent` inside automation PowerShell scripts. They are parsed from each script's captured output after the script completes and inserted in order.

| Context | Tier | `script_name` | `component` | When |
|---|---|---|---|---|
| `script` | `INFO` | `<name>.ps1` | value or null | `Write-HatchEvent "message"` — normal progress line |
| `script` | `WARN` | `<name>.ps1` | value or null | `Write-HatchEvent "message" -Tier WARN` — non-fatal advisory |
| `script` | `ERROR` | `<name>.ps1` | value or null | `Write-HatchEvent "message" -Tier ERROR` — caught failure |

The `component` column is populated from `-Component "label"` when passed to `Write-HatchEvent`. It is null when omitted.

Script events appear in the log interleaved with hatchery events, ordered by `id` (insertion order). Because `pywinrm` is blocking — the entire script runs before output is returned — all `Write-HatchEvent` lines from a script are inserted as a batch after the corresponding "Script complete" or "Script failed" hatchery event.

See [automations.md](automations.md#write-hatchevent) for `Write-HatchEvent` usage and the wire format (`[HATCH:TIER]` prefix).

<br>

---

<br>

## API

Events are exposed at:

```
GET /api/sessions/<session_id>/vms/<vm_name>/events
```

Returns a JSON array of event objects in insertion order:

```json
[
  {
    "id": 1,
    "context": "hatchery",
    "tier": "INFO",
    "script_name": null,
    "component": null,
    "message": "Hatching clutch: my-lab",
    "received_at": "2026-07-15T18:00:00+00:00"
  },
  {
    "id": 2,
    "context": "hatchery",
    "tier": "INFO",
    "script_name": null,
    "component": null,
    "message": "Creating VM: virt-install --name dc01 --memory 4096 ...",
    "received_at": "2026-07-15T18:00:01+00:00"
  },
  {
    "id": 5,
    "context": "script",
    "tier": "INFO",
    "script_name": "configure-vm-basics.ps1",
    "component": null,
    "message": "Setting timezone to Central Standard Time",
    "received_at": "2026-07-15T18:12:44+00:00"
  }
]
```

`received_at` is always stored in UTC. The [Settings](../docs/settings.md) pane lets you choose whether timestamps are displayed in UTC or converted to host local time — conversion happens in the UI using the `resolved_timezone` value from `/api/config`.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Where environments hatch</div>
<br clear="both">
