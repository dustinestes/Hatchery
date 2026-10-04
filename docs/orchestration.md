<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Orchestration Lifecycle</h1>
<br clear="both">

How Hatchery takes a Clutch definition from form submission to a fully provisioned, fledged VM.

<br>

## Contents

- [Contents](#contents)
- [Overview](#overview)
- [Phase 1 - VM Creation](#phase-1--vm-creation)
- [Phase 2 - OS Installation](#phase-2--os-installation)
- [Phase 3 - Setup Complete Handoff](#phase-3--setup-complete-handoff)
- [Phase 4 - Automation](#phase-4--automation)
- [VM Status Reference](#vm-status-reference)
- [Resilience and Retry](#resilience-and-retry)
- [Multi-VM Clutches](#multi-vm-clutches)

---

<br>

## Overview

Hatching a VM is a multi-phase process. Hatchery coordinates two distinct execution contexts - a background thread that creates VMs, and a polling loop that monitors them - to advance each VM through its lifecycle without blocking the UI or requiring user interaction.

```
Clutch submitted
       │
       ▼
 ┌─────────────┐
 │   hatching  │  ← virt-install running, Windows setup in progress
 └──────┬──────┘
        │  WinRM up + setup-complete flag present
        ▼
 ┌─────────────┐
 │ provisioning│  ← automation scripts running sequentially
 └──────┬──────┘
        │  all scripts exit 0
        ▼
 ┌─────────────┐
 │   fledged   │  ← VM is ready to use
 └─────────────┘
```

Failure at any phase lands the VM in `failed` status. The VM can be retried from the Nests panel, which replays the automation phase (not the OS install).

<br>

---

<br>

## Phase 1 - VM Creation

When the user submits a Clutch for hatching:

1. Hatchery creates a hatch session in the database and records each VM with status `pending`.
2. A background thread (`lib.hatch_lifecycle.run_hatch_session`) is spawned immediately. The UI redirects to the Nests pane without waiting.
3. For each VM in the Clutch, the thread:
   - Sets the VM status to `hatching`
   - Spawns a concurrent sub-thread (`_send_boot_key`) to handle the BIOS boot prompt
   - Calls `virt-install` to create and boot the VM

### Answer file

Windows guests require a selected Answer File (`answer_file` on the Clutch VM). Hatchery renders the Jinja template under `automation/answerfiles/` with reserved system tokens (`vm_name`, `admin_username`, `admin_password`) plus declared user parameters, then packs the result and any frontmatter companions into a 1.44 MB FAT floppy image using `mtools` (no root access required):

| File on floppy | Source | Purpose |
|---|---|---|
| `Autounattend.xml` | Rendered Answer File body | OS unattended install |
| Companion basenames (e.g. `hatchery-setup.ps1`) | Files listed in frontmatter `companions:` under `automation/answerfiles/` | First-boot orchestrator / extras |

The floppy is attached to the VM as a virtual floppy disk. Windows Setup detects `Autounattend.xml` on the floppy automatically and proceeds without user input.

Missing Answer File, missing companions, missing mandatory parameters, or a Nest that
does not support Answer File attach (`supports_answer_file_attach`) fail before
`virt-install`, with a clear UI/CLI error. See [Answer Files](answer-files.md) and
[ADR-0024](adr/0024-answer-files-product-model.md). Libvirt local floppy is the working
backend today; Hyper-V / UTM attach remain Planned ([providers.md](providers.md)).

The floppy image is **not** cleaned up on success - it must persist on disk until Windows installation is complete and the VM is destroyed. `destroy_vm` handles final cleanup.

### virt-install flags

| Flag | Purpose |
|---|---|
| `--cdrom <iso>` | OS installation media |
| `--disk path=<floppy>,device=floppy` | Answer file image |
| `--disk path=<virtio>,device=cdrom` | VirtIO drivers ISO (if configured) |
| `--boot uefi` | Win11 / Server 2025 only |
| `--tpm emulator,model=tpm-crb,version=2.0` | Win11 / Server 2025 only |
| `--noautoconsole` | Do not attach a console - Hatchery manages the VM headlessly |

### Boot prompt

Some BIOS/UEFI firmware displays a "Press any key to boot from CD/DVD" prompt when the VM first powers on. Libvirt reports the domain as `running` as soon as QEMU starts - often before that prompt appears - so Hatchery waits briefly after `running`, then sends `KEY_ENTER` via `virsh send-key` (100 ms holdtime) repeatedly for about 30 seconds to cover the prompt window. Transient send failures are ignored so an early miss does not abort the burst.

<br>

---

<br>

## Phase 2 - OS Installation

Windows Setup runs entirely unattended from the answer file. The process takes several minutes and involves multiple reboots.

### Boot cycle detection

Windows sends an ACPI power-off signal at certain points during setup (notably after initial file copy and after OOBE). From libvirt's perspective the VM simply shuts off - there is no signal distinguishing a setup reboot from a user shutdown.

Hatchery's background polling loop (`lib.hatch_lifecycle.sync_hatch_status`) runs on a configurable interval (default: 10 seconds) and detects when a VM in `hatching` status is shut off. It restarts the VM automatically via `virsh start`. This continues until Windows reaches the desktop and AutoLogon triggers.

This behaviour is **scoped to `hatching` status only**. Fledged VMs that are shut off are left alone. Script reboots during the automation phase use `Restart-Computer` (an in-guest restart) and never leave the VM in `shut off` state, so they do not interact with this mechanism.

<br>

---

<br>

## Phase 3 - Setup Complete Handoff

After the OS install finishes, Windows logs in automatically (via `AutoLogon`) and runs a single `<FirstLogonCommand>` from the answer file:

```
powershell.exe -ExecutionPolicy Bypass -File "A:\hatchery-setup.ps1"
```

This is the **stable contract** between the answer file and the orchestrator. If you ever edit the OS-specific answer file templates, the only line in `<FirstLogonCommands>` that must be preserved is this one.

### The orchestrator script (`hatchery-setup.ps1`)

`hatchery-setup.ps1` is a companion file under `automation/answerfiles/` (Library samples ship it next to the Autounattend templates). It is packed onto the floppy alongside `Autounattend.xml` when listed in Answer File frontmatter. It runs all setup steps sequentially inside a console window titled **"Hatchery - First Boot Setup"**, displaying a live progress list with step indicators:

| Indicator | Meaning |
|---|---|
| `[ ]` | Not yet started |
| `[>]` | Running |
| `[+]` | Succeeded |
| `[!]` | Failed |

The steps it executes, in order (OpenSSH path per [ADR-0029](adr/0029-guest-ssh-bootstrap-and-guest-transport.md)):

| Step | Action | Purpose |
|---|---|---|
| 1 | `Get-NetConnectionProfile \| Set-NetConnectionProfile -NetworkCategory Private` | Set network profile to Private (required for PSRemoting) |
| 2 | `Enable-PSRemoting -Force` (+ raise `MaxEnvelopeSizekb` to 8192 when lower) | Start the WinRM service and configure listeners; envelope headroom for Software staging |
| 3 | `New-ItemProperty … LocalAccountTokenFilterPolicy … 1` | Allow non-built-in admin accounts to authenticate over WinRM |
| 4 | `New-NetFirewallRule … -LocalPort 5985` | Open WinRM HTTP port |
| 5 | Download **latest** Win64 OpenSSH Server MSI from [PowerShell/Win32-OpenSSH](https://github.com/PowerShell/Win32-OpenSSH) and `msiexec … ADDLOCAL=Server` | Install OpenSSH Server under `C:\Program Files\OpenSSH` (not Windows Update FoD) |
| 6 | `Set-Service -Name sshd -StartupType Automatic` | Configure SSH to start on boot |
| 7 | `Start-Service -Name sshd` | Start SSH immediately |
| 8 | `New-NetFirewallRule … -LocalPort 22` | Open SSH port |
| 9 | `New-Item -Path 'C:\Program Files\Hatchery\temp\hatchery-ready' -ItemType File -Force` | **Setup-complete flag** |

**OpenSSH source (locked):** Hatchery does **not** use `Add-WindowsCapability -Online` / FoD for the default hatch path. Lab evidence: FoD often took ~15–20 minutes; the GitHub MSI completed download + install + service bring-up in ~9 seconds. Implementation resolves **latest** Win64 Server MSI at first boot. After early semver, Win32-OpenSSH has only shipped Beta then Preview tags (often ~a year old and still labeled Preview); Hatchery still tracks latest and documents that channel oddity here and in ADR-0029. Offline MSI staging is [#475](https://github.com/dustinestes/Hatchery/issues/475) / [#131](https://github.com/dustinestes/Hatchery/issues/131); Library release-asset → Software transform is [#517](https://github.com/dustinestes/Hatchery/issues/517). Guest Controller keys / `authorized_keys` are a follow-on; hatch auth for now remains admin password.

If any step fails, it is marked `[!]`, the failure message is displayed, and a "Press any key to close..." prompt is shown before the script exits with code 1. The console window remains open so the operator can read the error.

### The race condition and why the flag exists

WinRM becomes available as soon as step 2 completes - but OpenSSH install and later steps are still running. Without the flag, Hatchery would detect an open WinRM port and immediately begin running automation scripts while the OS setup was still in progress.

The `hatchery-ready` flag file is written as the **last step** of `hatchery-setup.ps1`. It means first-boot finished with OpenSSH installed, `sshd` listening, and TCP 22 open (ADR-0029). Hatchery's polling loop:

1. Confirms guest remoting TCP is open (SSH :22 or WinRM :5985 - cheap socket check)
2. Runs `Test-Path C:\Program Files\Hatchery\temp\hatchery-ready` over **Guest transport** (SSH preferred; WinRM Windows fallback) - see [guest transport](guest-transport.md) / [#497](https://github.com/dustinestes/Hatchery/issues/497)
3. Only advances to the next phase when the flag is present

The flag is **deleted immediately** upon detection - `Remove-Item` is called before any scripts run.

### Log file

`hatchery-setup.ps1` writes a structured log to `C:\Program Files\Hatchery\logs\hatchery-setup.log` as each step runs. Every line uses the same `[HATCH:LEVEL][component][timestamp] message` wire format as `Write-HatchEvent`, with guest-side UTC timestamps embedded per line. When Hatchery connects via Guest transport, it imports this log into `hatch_events` using the guest timestamps as `received_at` - so step durations are visible in the event log exactly as they happened - then deletes the file.

### Hatchery guest directory

`hatchery-setup.ps1` creates `C:\Program Files\Hatchery\` on first boot. Path roles (`root`, `logs`, `temp`, `software`, `software_package(id)`) are the cross-platform vocabulary; Windows absolute values are locked today. See [Software - Guest path roles](software.md#guest-path-roles), [ADR-0025](adr/0025-software-product-model.md), and guest env inject + persist [ADR-0026](adr/0026-guest-clutch-environment.md).

| Subdirectory | Contents |
|---|---|
| `logs\` | `hatchery-setup.log` (first-boot log); `<script-name>.log` (per-automation log, one per script); `software\{id}.log` (installer logs via `HATCHERY_SOFTWARE_LOG`) |
| `temp\` | Ephemeral files - currently only `hatchery-ready` (deleted immediately on detection) |
| `software\` | Staged installer payloads under `{package-id}\` when Software steps run ([Software](software.md)) |

Automation scripts also write to this directory via the injected `Write-HatchEvent` function. Each script gets its own log file named after the script (e.g. `configure-vm-basics.ps1.log`), created automatically.

If you want to remove all Hatchery artifacts from the guest after provisioning completes, add `hatchery-cleanup-windows.ps1` as the last entry in your Clutch's `automations` list (from [Hatchery Library](https://github.com/dustinestes/Hatchery-Library)). If omitted, the directory remains on the guest as a local audit record.

<br>

---

<br>

## Phase 4 - Automation

Once the setup-complete handoff occurs, Hatchery transitions the VM to `provisioning` and spawns a dedicated thread (`_provision_vm_thread`) to run the automation scripts.

### Clutch snapshot at hatch start

When a hatch session is created, Hatchery stores an immutable JSON copy of the Clutch on `hatch_sessions.clutch_snapshot` (#514). Automations were already copied into session DB rows; env persist, job inject, and Nest details for that session also read the snapshot. Editing the Clutch YAML (Build/Edit) during an active hatch affects only the **next** hatch, not the in-flight session. Legacy sessions without a snapshot still fall back to the live file.

### Guest environment persist (Windows)

Before the first automation runs, Hatchery persists reserved base Machine env vars (`HATCHERY_ROOT`, `HATCHERY_LOGS`, `HATCHERY_TEMP`, `HATCHERY_SOFTWARE`) plus Clutch user entries with `persist: true` (scope/mode per entry). Software-scoped vars stay job-only. Persist failure fails the hatch. Hatch events log the plan (`Persist: NAME → Machine|User (…)`) and a completion line before automations start. Each Script/Software job also gets process inject of reserved + Clutch vars for that job. See [ADR-0026](adr/0026-guest-clutch-environment.md).

### Script execution

Scripts run **sequentially** in the order they are declared in the Clutch file. For each script:

1. Status is set to `running` in the database
2. The script file is read from `~/.local/share/hatchery/automation/scripts/`
3. If the script has configured parameters, the content is wrapped in a PowerShell scriptblock: `& { param(...) <inject> <rest> } -Param 'value'`. The `param()` block is placed first (required by PowerShell), the `Write-HatchEvent` helper is injected after it, then the rest of the script body follows. Scripts without parameters receive the injection prepended directly with no wrapping. Reserved + Clutch user env are process-injected for the job.
4. The script is executed on the guest over WinRM via `pywinrm`
5. All stdout and stderr output is captured and stored against the script record
6. The exit code determines what happens next:

| Exit code | Outcome |
|---|---|
| `0` | Script marked `succeeded`; next script runs |
| Non-zero | Script marked `failed`; remaining scripts marked `skipped`; VM marked `failed` |

If a WinRM connection error occurs (e.g. the VM rebooted unexpectedly), the script is marked `failed` with exit code `-1` and provisioning halts.

### Reboot after

If a script has `reboot_after: true`, Hatchery captures the guest's `Win32_OperatingSystem.LastBootUpTime`, issues `Restart-Computer -Force` over WinRM, then polls until WinRM accepts an authenticated probe **and** `LastBootUpTime` differs from the pre-reboot value (`lib.provision.reboot_guest_and_wait`; [#499](https://github.com/dustinestes/Hatchery/issues/499)). After the boot identity changes, Hatchery requires several consecutive successful WinRM probes so the next step does not hit a half-ready remoting stack (common cause of WinRM "pipe has been ended" during Software staging). TCP alone is not enough: the pre-reboot OS often still accepts port 5985 before the restart completes. Timeout is 10 minutes for the boot-identity wait; failure aborts the hatch (no silent continue). Software `install.reboot_after` uses the same helper.

### Completion

When all scripts have succeeded, the VM is marked `fledged` and a hatch event is recorded. If the VM has no automation scripts at all, it is marked `fledged` immediately after the setup-complete handoff.

<br>

---

<br>

## VM Status Reference

| Status | Meaning |
|---|---|
| `pending` | VM is defined in the session but hatching has not started |
| `hatching` | `virt-install` has run; OS installation is in progress; boot-cycle restarts are active |
| `provisioning` | OS install is complete; automation scripts are running |
| `fledged` | All scripts succeeded (or no scripts were configured); VM is ready to use |
| `failed` | A script exited non-zero, a WinRM error occurred, or VM creation failed; retryable from the Nests panel |
| `culled` | The VM was destroyed (or disappeared from the host) while the session was active |

<br>

---

<br>

## Resilience and Retry

### App restart mid-provisioning

If Hatchery restarts while a VM is in `provisioning` status, the background polling loop detects the orphaned state on its next tick and re-spawns the provision thread. Scripts already marked `succeeded` are skipped; execution resumes from the first non-succeeded script.

Because a script that was `running` at restart time will be re-run from the beginning, **automation scripts should be written to be idempotent** - running a script twice should produce the same result as running it once. Most configuration operations (setting a registry value, installing a Chocolatey package, renaming the computer) are naturally idempotent. Operations that accumulate state (appending to a file, adding firewall rules without checking for duplicates) should include an existence check before acting.

### Manual retry

A `failed` VM can be retried from the Nests panel. Retry resets the status of every **non-succeeded** script (`failed`, `skipped`, `running`, `pending`) back to `pending` - scripts already marked `succeeded` are preserved and skipped during the re-run. This means:

- A script that failed partway through is re-run from the start
- Scripts that succeeded before the failure are not re-run
- The OS is not reinstalled - retry replays the automation phase only

Re-spawns the provision thread immediately if guest remoting TCP is reachable (SSH or WinRM), or queues it for the next polling tick if not.

<br>

---

<br>

## Multi-VM Clutches

When a Clutch defines multiple VMs, `run_hatch_session` creates them **sequentially** in the order they appear in the Clutch file. Each VM's `virt-install` call must complete before the next VM begins creation. Once created, all VMs are monitored concurrently by the polling loop and their automation phases run in parallel.

`depends_on` declarations are validated at Clutch load time (no unknown references, no cycles) and stored in the Clutch YAML, but **do not currently affect execution order**. Dependency-ordered hatching - waiting for a prerequisite VM to reach `fledged` before starting a dependent VM - is tracked in issue #123 and planned for a future release.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
