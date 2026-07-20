<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Automation Scripts</h1>
<br clear="both">

How to write, configure, and run automation scripts against guest VMs after first boot.

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
- [Parameter Introspection (pwsh)](#parameter-introspection-pwsh)
- [Clutch YAML Syntax](#clutch-yaml-syntax)
- [Example Files](#example-files)

---

<br>

## Overview

Automation scripts are PowerShell scripts that Hatchery executes against a guest VM over WinRM after it has completed its unattended Windows install. They are the primary mechanism for post-install provisioning — installing software, configuring the OS, renaming the machine, joining a domain, or anything else that needs to happen before a VM is considered fledged.

Scripts are stored in the `automation/scripts/` subdirectory of your Hatchery data directory (`~/.local/share/hatchery/automation/scripts/` by default). Any `.ps1` file placed there becomes available for selection in the Clutch builder.

Scripts are declared per VM in a Clutch file under the `automations` key and run in order. A failed script (non-zero exit code) halts provisioning for that VM — remaining scripts are skipped, and the VM is marked failed. Failed VMs can be retried from the Nests panel.

<br>

---

<br>

## How Hatchery Runs Scripts

Hatchery connects to the guest over WinRM using `pywinrm` and executes each script's content. The connection uses the admin credentials declared in the Clutch file.

Hatchery injects a `Write-HatchEvent` helper function into every script before execution. You do not need to define it, source it, or import it — it is always available. See [Write-HatchEvent](#write-hatchevent).

If the script declares parameters (see [Parameters](#parameters)), Hatchery wraps the content in a PowerShell scriptblock and appends the configured values as named arguments. PowerShell requires `param()` to be the first statement inside a scriptblock, so Hatchery places it first, injects `Write-HatchEvent` immediately after, then appends the rest of the script:

```powershell
& {
    param($ComputerName, $TimeZone)   # param() block — must be first
    function Write-HatchEvent { ... } # injected by Hatchery
    # ... rest of script ...
} -ComputerName 'dc01' -TimeZone 'Central Standard Time'
```

Scripts without parameters receive the same `Write-HatchEvent` injection prepended directly, with no scriptblock wrapping.

All script output (stdout and stderr) is captured and stored per-script in the database. The exit code is read when the script finishes:

| Exit code | Meaning |
|---|---|
| `0` | Success — next script runs, or VM is marked fledged if this was the last |
| `> 0` | Failure — provisioning halts, remaining scripts are skipped, VM is marked failed |

The actual non-zero exit code is stored and shown in the Nests panel, so you can use specific codes (e.g. `exit 2`, `exit 99`) for diagnostic purposes.

If `reboot_after: true` is set for a script, Hatchery reboots the VM after the script succeeds and waits for WinRM to become available again before running the next script. This is required for operations like computer rename that only take effect after a restart.

<br>

---

<br>

## Writing Scripts

### Write-HatchEvent

Hatchery injects a `Write-HatchEvent` helper function into every script before execution (see [How Hatchery Runs Scripts](#how-hatchery-runs-scripts) for placement details). You do not need to define it, source it, or import it — it is always available.

```powershell
Write-HatchEvent -Message "text" [-Tier INFO|WARN|ERROR] [-Component "label"]
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `-Message` | string | *(required)* | The log line to emit |
| `-Tier` | `INFO` \| `WARN` \| `ERROR` | `INFO` | Severity level — controls styling in the event log |
| `-Component` | string | *(none)* | Optional sub-label grouping related lines (e.g. `"Chocolatey"`, `"Registry"`) |

**Tiers:**

| Tier | When to use |
|---|---|
| `INFO` | Normal progress — steps starting, completing, values confirmed |
| `WARN` | Non-fatal advisory — fallback taken, optional step skipped, value defaulted |
| `ERROR` | Failure you caught but want flagged — the exit code still controls the actual outcome |

**Examples:**

```powershell
# Simple progress line
Write-HatchEvent "Installing Chocolatey"

# With a component label to group related lines in the feed
Write-HatchEvent "Installing git" -Component "Chocolatey"

# Non-fatal advisory
Write-HatchEvent "Registry key not found, using default value" -Tier WARN -Component "Registry"

# Caught error (still exit non-zero to mark the script failed)
Write-HatchEvent "Installation failed: $_" -Tier ERROR -Component "Chocolatey"
exit 1
```

`Write-HatchEvent` emits lines in the format `[HATCH:TIER] message` or `[HATCH:TIER][Component] message`. Hatchery parses these after each script completes and stores them as individual events in the database.

The parser also accepts an optional ISO timestamp bracket: `[HATCH:TIER][Component][2026-07-20T12:34:56Z] message`. When present, the timestamp is stored as `received_at` instead of the host clock — this is used by the first-boot setup log (`hatchery-setup.log`) so guest-side step timing is preserved on import. User automation scripts do not need to include timestamps.

> **Note:** Use `Write-HatchEvent` in place of bare `Write-Output` for any line you want visible in the event log. Raw `Write-Output` lines are captured in the script's stored output but do not appear as structured feed events.

<br>

### Conventions

Follow these conventions to ensure your scripts work reliably with Hatchery:

**Use `Write-HatchEvent` for progress lines.** Lines emitted through `Write-HatchEvent` appear as structured events in the event log with tier styling and optional component labels. Avoid bare `Write-Host` — it targets the information stream (stream 6) and may not be captured depending on the Windows version and WinRM setup.

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
    Write-HatchEvent "Script failed: $_" -Tier ERROR
    exit 1
}
```

<br>

### Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | General failure (use in `catch` blocks) |
| `2`–`255` | Custom diagnostic codes — stored and displayed in the Nests panel |

<br>

### Parameters

Scripts can declare a `param()` block to accept configurable inputs. Hatchery reads two PowerShell parameter attributes:

| Attribute | Effect in Hatchery |
|---|---|
| `Mandatory = $true` | Field is marked required in the Clutch builder UI; saving is blocked until a value is provided |
| `HelpMessage = "..."` | Shown as tooltip text on the help icon next to the field in the UI |

PowerShell's built-in common parameters (`Verbose`, `Debug`, `ErrorAction`, `WarningAction`, `InformationAction`, `ProgressAction`, `WhatIf`, `Confirm`, and related variable parameters) are automatically excluded from the Hatchery UI — they are injected by the PowerShell runtime and are not user-configurable via the Clutch builder.

Example parameter block:

```powershell
param(
    [Parameter(Mandatory = $true, HelpMessage = "New name for this computer. Must be 15 characters or fewer.")]
    [ValidateLength(1, 15)]
    [string]$ComputerName,

    [Parameter(Mandatory = $false, HelpMessage = "Windows timezone ID, e.g. 'Central Standard Time'. Defaults to UTC if not set.")]
    [string]$TimeZone = "UTC"
)
```

Parameters with a default value are optional in the UI — the field is pre-populated with the default and can be left as-is or overridden per-VM in the Clutch builder.

<br>

---

<br>

## Parameter Introspection (pwsh)

To automatically discover and render parameter fields in the Clutch builder UI, Hatchery needs `pwsh` (PowerShell Core) installed on the **Ubuntu host** — not the guest VM. When `pwsh` is available, Hatchery runs:

```bash
pwsh -Command "(Get-Command <script-path>).Parameters.Values | ConvertTo-Json"
```

This introspects the script's `param()` block and returns metadata (name, mandatory flag, help message, default value) that Hatchery uses to render the appropriate input fields in the Clutch builder.

**`pwsh` is optional.** If it is not installed, you can still use automation scripts — you just configure parameters manually in the Clutch YAML file under each script's `parameters` key. The Clutch builder will still show scripts in the automations list, but no inline parameter fields will be rendered for them.

**Installing `pwsh` on Ubuntu:**

```bash
# Install the Microsoft package feed, then:
sudo apt-get install -y powershell
```

Full installation instructions: [https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell-on-linux](https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell-on-linux)

After installation, the Requirements check in the Settings pane will show `pwsh` as satisfied and parameter introspection will activate automatically.

<br>

---

<br>

## Clutch YAML Syntax

The `automations` key under a VM accepts a list of scripts. Each entry is either a plain script name (no parameters, no reboot) or an object with optional `parameters` and `reboot_after` keys.

**Simple form** — no parameters, no reboot:

```yaml
automations:
  - configure-vm-basics.ps1
  - install-dev-tools.ps1
```

**Object form** — with parameters and/or reboot:

```yaml
automations:
  - name: configure-vm-basics.ps1
    reboot_after: true
    parameters:
      ComputerName: dc01
      TimeZone: "Central Standard Time"
  - name: install-dev-tools.ps1
```

You can mix both forms freely in the same list. Hatchery normalizes them on load.

| Key | Type | Default | Description |
|---|---|---|---|
| `name` | string | — | Filename of the script in `automation/scripts/` |
| `reboot_after` | boolean | `false` | Reboot the VM after this script succeeds before running the next |
| `parameters` | map | `{}` | Named values passed to the script's `param()` block |

<br>

---

<br>

## Example Files

Two example files ship with Hatchery under `.hatchery/examples/scripts/`:

| File | Purpose |
|---|---|
| [`hatchery-script-template.ps1`](../examples/scripts/hatchery-script-template.ps1) | Commented template showing all conventions, a sample `param()` block, `Write-HatchEvent` usage, and the `try/catch/exit` pattern |
| [`configure-vm-basics.ps1`](../examples/scripts/configure-vm-basics.ps1) | Real working script — renames the computer and sets the timezone; demonstrates `Mandatory`, `HelpMessage`, `ValidateLength`, and `reboot_after` usage |

Copy either file to your `automation/scripts/` directory as a starting point. The template is the recommended starting point for new scripts; `configure-vm-basics.ps1` is ready to use as-is.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Where environments hatch</div>
<br clear="both">
