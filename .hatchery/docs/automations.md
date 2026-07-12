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

If the script declares parameters (see [Parameters](#parameters)), Hatchery wraps the script content in a PowerShell scriptblock and appends the configured values as named arguments:

```powershell
& {
    <script content>
} -ComputerName 'dc01' -TimeZone 'Central Standard Time'
```

All script output (stdout and stderr) is captured and streamed to the Nests panel in real time. The exit code is read when the script finishes:

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

### Conventions

Follow these conventions to ensure your scripts work reliably with Hatchery:

**Use `Write-Output` for progress lines**, not `Write-Host`. `Write-Output` targets the success stream (stream 1) and is reliably captured by Hatchery across all WinRM configurations. `Write-Host` targets the information stream (stream 6) and may not be captured depending on the Windows version and WinRM setup.

**Set `$ErrorActionPreference = "Stop"`** at the top of every script. This turns unhandled cmdlet errors into terminating exceptions that your `try/catch` block can catch. Without it, many cmdlets write to the error stream and continue, leaving your script in an unknown state.

**Wrap the main body in `try/catch`** and call `exit 1` in the `catch` block. This ensures a clean non-zero exit code on failure rather than relying on PowerShell's implicit exit behavior.

**Keep each script focused on one concern.** Compose behavior via the `automations` list in your Clutch file, not by chaining logic inside a single script. Smaller scripts are easier to retry, reorder, and reuse across different Clutches.

A minimal script skeleton:

```powershell
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] $Message"
}

try {
    Write-Step "Script started"

    # --- work goes here ---

    Write-Step "Script completed successfully"
    exit 0

} catch {
    Write-Error "[ERROR] $_"
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
| [`hatchery-script-template.ps1`](../examples/scripts/hatchery-script-template.ps1) | Commented template showing all conventions, a sample `param()` block, the `Write-Step` helper, and the `try/catch/exit` pattern |
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
