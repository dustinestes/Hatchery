<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Automation Scripts</h1>
<br clear="both">

How to write, configure, and run automation scripts against guest VMs after first boot. For typed Clutch parameter kinds, constraints, and invoke encoding, see [Script parameters](script-parameters.md). For guest application packages, see [Software](software.md). For install-time unattended templates, see [Answer Files](answer-files.md).

<br>

## Contents

- [Contents](#contents)
- [Overview](#overview)
- [How Hatchery Runs Scripts](#how-hatchery-runs-scripts)
- [Writing Scripts](#writing-scripts)
  - [Write-HatchEvent](#write-hatchevent)
  - [Conventions](#conventions)
  - [Exit Codes](#exit-codes)
  - [Parameters](#parameters)
- [Clutch YAML Syntax](#clutch-yaml-syntax)
  - [Migration from bare-string automations](#migration-from-bare-string-automations)
- [Example Files](#example-files)
  - [VirtIO driver automation](#virtio-driver-automation)
- [Related](#related)

---

<br>

## Overview

Automation scripts are PowerShell scripts that Hatchery executes against a guest VM over guest remoting (SSH primary; WinRM Windows fallback - [Guest transport](guest-transport.md)) after it has completed its unattended Windows install. They are the primary mechanism for post-install provisioning - installing software, configuring the OS, renaming the machine, joining a domain, or anything else that needs to happen before a VM is considered fledged.

Scripts are stored in the `automation/scripts/` subdirectory of your Hatchery data directory (`~/.local/share/hatchery/automation/scripts/` by default). Add scripts with **Import** on Automations → Scripts, or place files there on the Nest; remove them with the trash control in the script detail header. Any `.ps1` (and other supported script types) becomes available for selection in the Clutch builder. The Automations → Scripts pane inventories those files for discovery and audit (metadata, Clutch usage, read-only content, copy path) - editing stays in your host editor.

Scripts are declared per VM in a Clutch file under the `automations` key and run in order. A failed script (non-zero exit code) halts provisioning for that VM - remaining scripts are skipped, and the VM is marked failed. Failed VMs can be retried from the Nests panel.

<br>

---

<br>

## How Hatchery Runs Scripts

Hatchery connects to the guest over guest remoting (SSH primary; WinRM Windows fallback) and executes each script's content. Auth uses the Clutch admin credentials and, when SSH is authorized, Controller remoting identities ([Guest transport](guest-transport.md)).

`Write-HatchEvent` comes from the Hatchery PowerShell module installed by the guest environment ensure job (`HATCHERY_ROOT\modules\Hatchery`, on `PSModulePath`). You do not need to define it, source it, or import it - PowerShell autoloads it. Hatchery does **not** splice helper function bodies into your script text. See [Write-HatchEvent](#write-hatchevent).

If the script declares parameters (see [Parameters](#parameters) and [Script parameters](script-parameters.md)), Hatchery wraps the **user** content in a PowerShell scriptblock and appends the Clutch values as named arguments (typed encoding when introspection metadata exists). Reserved / Clutch process env is applied in an outer scope so `param()` stays first inside your scriptblock:

```powershell
$env:HATCHERY_ROOT = '...'   # outer scope (Hatchery process env)
# ...
& {
    param($ComputerName, $TimeZone)   # your param() block - first in the user scriptblock
    # ... your script body unchanged ...
} -ComputerName 'dc01' -TimeZone 'Central Standard Time'
```

Scripts that declare `param()` but have no Clutch parameter values still keep `param()` first inside a user scriptblock when process env is present. Scripts with no `param()` block run as authored after the outer env preamble.

All script output (stdout and stderr) is captured and stored per-script in the database. The exit code is read when the script finishes:

| Exit code | Meaning |
|---|---|
| `0` | Success - next script runs, or VM is marked fledged if this was the last |
| `> 0` | Failure - provisioning halts, remaining scripts are skipped, VM is marked failed |

The actual non-zero exit code is stored and shown in the Nests panel, so you can use specific codes (e.g. `exit 2`, `exit 99`) for diagnostic purposes.

If `reboot_after: true` is set for a script, Hatchery reboots the VM after the script succeeds and waits until the guest reports a new `LastBootUpTime` (not merely TCP SSH/WinRM) before running the next script. This is required for operations like computer rename that only take effect after a restart.

<br>

---

<br>

## Writing Scripts

### Write-HatchEvent

`Write-HatchEvent` is exported by the Hatchery guest module installed during ensure (`$env:HATCHERY_MODULES\Hatchery`, on Machine `PSModulePath` for Windows PowerShell and pwsh). You do not need to define it, source it, or import it - call it like any other cmdlet (#554 / ADR-0032).

```powershell
Write-HatchEvent -Message "text" [-Level INFO|WARN|ERROR] [-Component "label"]
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `-Message` | string | *(required)* | The log line to emit |
| `-Level` | `INFO` \| `WARN` \| `ERROR` | `INFO` | Event level - controls styling in the event log |
| `-Component` | string | *(none)* | Optional sub-label grouping related lines (e.g. `"Chocolatey"`, `"Registry"`) |

**Levels:**

| Level | When to use |
|---|---|
| `INFO` | Normal progress - steps starting, completing, values confirmed |
| `WARN` | Non-fatal advisory - fallback taken, optional step skipped, value defaulted |
| `ERROR` | Failure you caught but want flagged - the exit code still controls the actual outcome |

**Examples:**

```powershell
# Simple progress line
Write-HatchEvent "Installing Chocolatey"

# With a component label to group related lines in the feed
Write-HatchEvent "Installing git" -Component "Chocolatey"

# Non-fatal advisory
Write-HatchEvent "Registry key not found, using default value" -Level WARN -Component "Registry"

# Caught error (still exit non-zero to mark the script failed)
Write-HatchEvent "Installation failed: $_" -Level ERROR -Component "Chocolatey"
exit 1
```

`Write-HatchEvent` emits lines in the format `[HATCH:LEVEL] message` or `[HATCH:LEVEL][Component] message`. Hatchery parses these after each script completes and stores them as individual events in the database.

Internally it writes the transcript line with `[Console]::Out.WriteLine` (not `Write-Output`) so events stay on remoting stdout even when a helper’s return value is captured (`if (Helper) { }`). It also tees a timestamped copy to the guest job log: `$env:HATCHERY_SCRIPT_LOG` when set (per-script under `HATCHERY_LOGS`), otherwise `HATCHERY_LOGS\hatchery-events.log` (#574).

The parser also accepts an optional ISO timestamp bracket: `[HATCH:LEVEL][Component][2026-07-20T12:34:56+00:00] message`. When present, the timestamp is stored as `received_at` instead of the host clock - this is used by the first-boot setup log (`hatchery-setup-windows.log`) so guest-side step timing is preserved on import. The timestamp uses the same `+00:00` UTC form as host-written events. User automation scripts do not need to include timestamps.

> **Note:** Use `Write-HatchEvent` in place of bare `Write-Output` for any line you want visible in the event log. Raw `Write-Output` lines are captured in the script's stored output but do not appear as structured feed events. Do not implement your own progress helpers with `Write-Output` if those helpers also return values - use `Write-HatchEvent` so logging never pollutes the success pipeline.

<br>

### Conventions

Follow these conventions to ensure your scripts work reliably with Hatchery:

**Use `Write-HatchEvent` for progress lines.** Lines emitted through `Write-HatchEvent` appear as structured events in the event log with level styling and optional component labels. Avoid bare `Write-Host` - it targets the information stream (stream 6) and may not be captured depending on the Windows version and WinRM setup.

**Set `$ErrorActionPreference = "Stop"`** at the top of every script. This turns unhandled cmdlet errors into terminating exceptions that your `try/catch` block can catch. Without it, many cmdlets write to the error stream and continue, leaving your script in an unknown state.

**Wrap the main body in `try/catch`** and call `exit 1` in the `catch` block. This ensures a clean non-zero exit code on failure rather than relying on PowerShell's implicit exit behavior.

**Keep each script focused on one concern.** Compose behavior via the `automations` list in your Clutch file, not by chaining logic inside a single script. Smaller scripts are easier to retry, reorder, and reuse across different Clutches.

A minimal script skeleton:

```powershell
$ErrorActionPreference = "Stop"

try {
    Write-HatchEvent "Script started"

    # --- work goes here ---

    Write-HatchEvent "Script completed successfully"
    exit 0

} catch {
    Write-HatchEvent "Script failed: $_" -Level ERROR
    exit 1
}
```

<br>

### Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | General failure (use in `catch` blocks) |
| `2`–`255` | Custom diagnostic codes - stored and displayed in the Nests panel |

<br>

### Parameters

Scripts can declare a `param()` block to accept configurable inputs. Hatchery introspects declared types and constraints (when Controller `pwsh` is available) and renders matching Clutch fields. Full kind / constraint / encode reference: **[Script parameters](script-parameters.md)** ([ADR-0034](adr/0034-script-param-discover-dont-invent.md), [#571](https://github.com/dustinestes/Hatchery/issues/571)).

Minimal example:

```powershell
param(
    [Parameter(Mandatory = $true, HelpMessage = "New name for this computer. Must be 15 characters or fewer.")]
    [ValidateLength(1, 15)]
    [string]$ComputerName,

    [Parameter(Mandatory = $false, HelpMessage = "Windows timezone ID, e.g. 'Central Standard Time'. Defaults to UTC if not set.")]
    [string]$TimeZone = "UTC"
)
```

Parameters with a default value are optional in the UI - the field is pre-populated with the default and can be left as-is or overridden per-VM in the Clutch builder.

PowerShell **parameter sets** (`ParameterSetName`) are not supported: Hatchery flattens all declared params into one form. Prefer a single flat `param()` for Clutch scripts until that lands. Details: [Script parameters - PowerShell parameter sets](script-parameters.md#powershell-parameter-sets).

<br>

---

<br>

## Clutch YAML Syntax

The `automations` key under a VM is an **ordered** list of typed entries. Every entry must declare `type: script` or `type: software` plus `name` ([ADR-0025](adr/0025-software-product-model.md), [#473](https://github.com/dustinestes/Hatchery/issues/473)). Bare string script names are **not** accepted (pre-release break).

**Script** (optional `parameters` / `reboot_after`):

```yaml
automations:
  - type: script
    name: configure-vm-basics.ps1
    reboot_after: true
    parameters:
      ComputerName: dc01
      TimeZone: "Central Standard Time"
  - type: script
    name: install-dev-tools.ps1
```

**Mixed Scripts and Software:**

```yaml
automations:
  - type: script
    name: configure-vm-basics.ps1
  - type: software
    name: Hatchery.SoftwareExample.1.0.0
    clean_payload_on_success: true
  - type: script
    name: enable-rdp-windows.ps1
    reboot_after: true
```

| Key | Type | Default | Applies to | Description |
|---|---|---|---|---|
| `type` | `script` \| `software` | required | both | Automation kind |
| `name` | string | required | both | Script basename under `automation/scripts/`, or package id under `automation/software/` |
| `reboot_after` | boolean | `false` | both | Reboot the VM after this step succeeds before running the next |
| `parameters` | map | `{}` | script only | Named values for the script's declared params (typed natives preferred: bool/number/string) |
| `clean_payload_on_success` | boolean | `true` | software only | Remove staged installer payload after a successful install |

Software hatch execution (stage → install → optional clean) is tracked in [#474](https://github.com/dustinestes/Hatchery/issues/474). Until then, Software rows are saved on the Clutch and shown in the form; hatch logs a warning and skips running them.

### Migration from bare-string automations

If an older Clutch used:

```yaml
automations:
  - configure-vm-basics.ps1
```

rewrite each entry to:

```yaml
automations:
  - type: script
    name: configure-vm-basics.ps1
```

Or open the Clutch in **Edit**, re-add each script from the Scripts picker, and save.

<br>

---

<br>

## Example Files

Sample scripts, Clutches, and media ship in the public **[Hatchery Library](https://github.com/dustinestes/Hatchery-Library)** repo. Add it as a Forge connection and pull into the operator cache (see [Library - Forge connections](library.md#forge-connections-307)).

| File (Windows) | Purpose |
|---|---|
| [`hatchery-script-template-windows.ps1`](https://github.com/dustinestes/Hatchery-Library/blob/main/scripts/windows/hatchery-script-template-windows.ps1) | Commented template showing all conventions, a sample `param()` block, `Write-HatchEvent` usage, and the `try/catch/exit` pattern |
| [`configure-vm-basics-windows.ps1`](https://github.com/dustinestes/Hatchery-Library/blob/main/scripts/windows/configure-vm-basics-windows.ps1) | Real working script - renames the computer and sets the timezone; demonstrates `Mandatory`, `HelpMessage`, `ValidateLength`, and `reboot_after` usage |
| [`test-param-smoke-windows.ps1`](https://github.com/dustinestes/Hatchery-Library/blob/main/tests/scripts/windows/test-param-smoke-windows.ps1) | Test fixture for typed Clutch params ([#571](https://github.com/dustinestes/Hatchery/issues/571)): string + `ValidateSet` / `ValidateLength`, `[bool]`, `[switch]`, `[int]`, `[double]`. Under `tests/scripts/` (opt-in **Test Scripts** binding, [#573](https://github.com/dustinestes/Hatchery/issues/573)). Dumps bound values via `Write-HatchEvent`, stdout, and a guest file under `HATCHERY_LOGS` |
| [`enable-rdp-windows.ps1`](https://github.com/dustinestes/Hatchery-Library/blob/main/scripts/windows/enable-rdp-windows.ps1) | Enables Remote Desktop and the firewall group; optional `RdpUsers` (comma-separated) adds non-admin accounts to Remote Desktop Users (Administrators already have RDP access) |
| [`remove-appx-windows.ps1`](https://github.com/dustinestes/Hatchery-Library/blob/main/scripts/windows/remove-appx-windows.ps1) | Removes AppX packages by `PackageNames`, or removable non-framework packages when `RemoveAll` is true; `KeepPackageNames` / `KeepDefaults` skip lab keepers |
| [`install-virtio-drivers-windows.ps1`](https://github.com/dustinestes/Hatchery-Library/blob/main/scripts/windows/install-virtio-drivers-windows.ps1) | Installs VirtIO guest tools / drivers from the attached VirtIO ISO (`DriveLetter` or `IsoLabel`); see [VirtIO driver automation](#virtio-driver-automation) |
| [`hatchery-cleanup-windows.ps1`](https://github.com/dustinestes/Hatchery-Library/blob/main/scripts/windows/hatchery-cleanup-windows.ps1) | Restores UAC lowered at first boot ([#543](https://github.com/dustinestes/Hatchery/issues/543)), removes `C:\Program Files\Hatchery\`, and clears persisted reserved Machine env; add as the last automation if you want no Hatchery artifacts left after provisioning |

Linux and macOS counterparts live under `scripts/linux/` and `scripts/macos/` in the same repo (unique basenames with `-linux` / `-macos` suffixes).

Pull into `automation/scripts/` via Library, or download a starting point manually. The Windows template is the recommended starting point for new PowerShell scripts.

Prefer YAML natives that match the script (see [Script parameters - YAML and invoke encoding](script-parameters.md#yaml-and-invoke-encoding)). For multi-value string inputs (`RdpUsers`, `PackageNames`), pass a comma-separated list.

<br>

### VirtIO driver automation

VirtIO drivers improve disk and network performance for Windows guests but are **optional**. Guests on IDE/e1000 do not need them.

Full flow when you do want VirtIO:

1. Import a [virtio-win](https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/) ISO under **Media → VirtIO** (or pull the slim sample from [Hatchery Library](https://github.com/dustinestes/Hatchery-Library) Media → VirtIO).
2. In the Clutch / Hatch form, set the **VirtIO Drivers** field to that ISO. Hatchery attaches it as a secondary CD-ROM at hatch time and configures VirtIO disk/network adapters.
3. Pull [`install-virtio-drivers-windows.ps1`](https://github.com/dustinestes/Hatchery-Library/blob/main/scripts/windows/install-virtio-drivers-windows.ps1) into `automation/scripts/` and add it to the VM's `automations` list with either `DriveLetter` (e.g. `E`) or `IsoLabel` (default `virtio-win`):

```yaml
automations:
  - type: script
    name: install-virtio-drivers-windows.ps1
    parameters:
      IsoLabel: virtio-win
```

4. After OS install, Hatchery runs the script over guest remoting. Prefer the guest-tools MSI when present on the ISO; otherwise it falls back to `pnputil` plus the QEMU guest agent MSI under `guest-agent\`.

Also covered in [Getting started - VirtIO Drivers](getting-started.md#virtio-drivers).

<br>

---

<br>

## Related

- [Script parameters](script-parameters.md) - kinds, constraints, gates, invoke encoding
- [Software](software.md) - post-boot guest packages (ordered with Scripts in Clutch `automations`)
- [ADR-0025](adr/0025-software-product-model.md) - Software product model
- [Answer Files](answer-files.md) - install-time templates (not Scripts)
- [ADR-0024](adr/0024-answer-files-product-model.md) - Answer Files product model

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
