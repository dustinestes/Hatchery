<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Answer Files</h1>
<br clear="both">

Install-time templates for unattended guest OS setup - distinct from post-boot [Automation Scripts](automations.md).

<br>

## Contents

- [Contents](#contents)
- [Overview](#overview)
- [Answer Files vs Scripts](#answer-files-vs-scripts)
- [Storage and Library](#storage-and-library)
- [System tokens and parameters](#system-tokens-and-parameters)
- [Clutch fields](#clutch-fields)
- [Companions](#companions)
- [Windows](#windows)
- [Linux](#linux)
- [macOS](#macos)
- [Nest attach](#nest-attach)
- [Architecture](#architecture)
- [Example files](#example-files)

---

<br>

## Overview

**Answer Files** are templates Hatchery renders at hatch time and attaches as install media so the guest OS installer can run unattended. They live under `automation/answerfiles/` in the Hatchery data directory.

Product shape is locked in [ADR-0024](adr/0024-answer-files-product-model.md). Windows guests require a selected Answer File on the Clutch; Hatchery renders system tokens and declared parameters from that file (no Controller shadow templates).

<br>

---

<br>

## Answer Files vs Scripts

| | Answer Files | Automation Scripts |
|---|---|---|
| When | During OS install / first-boot media | After the guest is reachable (fledged path) |
| Who consumes | Guest **installer** / early boot | Guest shell (WinRM today; SSH later) |
| Data dir | `automation/answerfiles/` | `automation/scripts/` |
| Nest role | Pack and **attach** media | Transfer and **run** |
| Parameters | Declared frontmatter; Jinja `{{ name }}` | PowerShell `param()` (+ optional pwsh introspect) |

<br>

---

<br>

## Storage and Library

- Place files in `automation/answerfiles/` (Import on Automations → Answer Files, or drop files there on the Controller). Library pull for the `answerfiles` domain is live: on a fresh Controller the Hatchery Library seed includes an **All Answer Files** binding; pull from Library → Content Available (or `hatchery library content pull --domain answerfiles`).
- Optional samples ship in the public [Hatchery-Library](https://github.com/dustinestes/Hatchery-Library) repo under `answerfiles/windows/`. That repo is **content only**. Pull or import only if you want Hatchery’s examples; nothing is auto-copied into your data dir.
- Automations → Answer Files inventories those files for discovery and audit (metadata, Clutch usage, read-only content, copy path) - editing stays in your host editor.

<br>

---

<br>

## System tokens and parameters

### Reserved system tokens

Injected from the Clutch VM / hatch session. Do **not** declare these as user parameters:

| Token | Source |
|---|---|
| `vm_name` | VM name (Windows ComputerName may truncate) |
| `admin_username` | Admin Username on the VM (when Guest OS needs hatch creds) |
| `admin_password` | Admin password supplied at hatch time |

Admin Username / Password remain first-class Clutch / hatch fields when the selected Guest OS needs them for hatch through fledged. The Clutch Build/Edit form shows **Admin Username** and **Answer File** only for Windows guests (`win10`, `win11`, `server2022`, `server2025`); both are required when that section is visible. Other Guest OS values hide those fields and strip them on save.

### Hatch-scoped through fledged

Those credentials exist so Hatchery can:

1. Inject reserved tokens into the Answer File (local admin / AutoLogon during install)
2. Authenticate guest WinRM while Automation Scripts run until the VM reaches **fledged**

They are **not** Hatchery’s long-term manage credential for the guest after fledged. Product intent (ADR-0024): hatch-scoped through fledged; post-fledged rotation and hardening are the operator’s job.

| After fledged | Guidance |
|---|---|
| Rotate / harden the hatch admin | Add a final Clutch automation (or out-of-band change) that sets a new password and records it in your secrets store |
| Hatchery-Library cleanup scripts | [`hatchery-cleanup-windows.ps1`](https://github.com/dustinestes/Hatchery-Library/blob/main/scripts/windows/hatchery-cleanup-windows.ps1) removes guest Hatchery artifacts under `C:\Program Files\Hatchery\`; it does **not** rotate the admin password |
| Inventory Username / Password | May still show the hatch values (password display is opt-in in Settings) until the hatch session is archived - treat that as hatch history, not the guest’s ongoing secret of record |
| Encrypted credential storage | Out of scope here; tracked in [#110](https://github.com/dustinestes/Hatchery/issues/110) |

See also [Credential storage](schema/database.md#credential-storage).

### User-declared parameters

Declared in YAML frontmatter under `hatchery.parameters`. Shown on the Clutch builder like script parameters. Example: locales (`input_locale`, `system_locale`, `ui_language`, `user_locale`).

Each entry supports:

| Key | Meaning |
|---|---|
| `name` | Required. Jinja token name. Reserved system tokens are skipped. |
| `label` | Optional display label (and help tooltip). Falls back to `name` in the UI. |
| `default` | Optional default shown as placeholder; may be prefilled by the operator. |
| `mandatory` | Optional. Default `false`. When true and no default, the field is required. |

Substitution uses Jinja: `{{ input_locale }}` in the template body.

Frontmatter:

```yaml
---
hatchery:
  kind: windows_unattend
  guest_os: [win11]
  companions:
    - hatchery-setup.ps1
  parameters:
    - name: input_locale
      label: Input locale
      default: en-US
    - name: system_locale
      label: System locale
      default: en-US
    - name: ui_language
      label: UI language
      default: en-US
    - name: user_locale
      label: User locale
      default: en-US
---
```

<br>

---

<br>

## Clutch fields

| Field | Meaning |
|---|---|
| `answer_file` | Filename under `automation/answerfiles/` ending in `.j2` (Jinja template). Companions (e.g. `hatchery-setup.ps1`) are not listed in the Clutch picker. Legacy Clutch key `os_config` is still accepted on load. |
| `answer_file_parameters` | Map of user-declared param values for that file (from frontmatter `hatchery.parameters`) |
| `admin_username` / hatch password | Required for Windows guests (`admin_username` on the Clutch; password at hatch). Feed system tokens when the Guest OS needs them |

When Answer Files are required for a guest type, missing `answer_file` or a missing required declared param fails before VM create, with a clear UI/CLI error. Admin credentials no longer select a hidden Controller template.

<br>

---

<br>

## Companions

An Answer File may list **companion** files in frontmatter (for example `hatchery-setup.ps1`). Hatchery packs companions onto the same attach media as the rendered unattend.

For Windows samples, Autounattend `FirstLogonCommands` should launch the companion (today: `powershell.exe … -File "A:\hatchery-setup.ps1"` on the floppy drive letter used by the Nest packer). That contract belongs in the Answer File you author, not in invisible Controller code.

<br>

---

<br>

## Windows

Supported Guest OS values today: `win10`, `win11`, `server2022`, `server2025`.

### What the installer expects

Windows Setup looks for **Autounattend.xml** on attach media. Hatchery packs the rendered template under that name for Nest attach.

Typical content in Hatchery’s samples:

- Disk layout (BIOS-style single partition for Win10; EFI/MSR/Windows for Win11 / Server 2025 paths)
- `ComputerName` from `{{ vm_name }}`
- Local admin account and AutoLogon from `{{ admin_username }}` / `{{ admin_password }}`
- Locale settings (user params in samples; hard-coded `en-US` in older shadow templates)
- Single FirstLogonCommand that runs `hatchery-setup.ps1` (WinRM, OpenSSH, `hatchery-ready` flag)

UEFI + TPM remain a Nest/provider concern for Win11 and Server 2025 ([`docs/providers.md`](providers.md)).

### Per OS notes

| Guest OS | Notes |
|---|---|
| Win10 | Legacy partition layout in the sample; floppy attach on libvirt today |
| Win11 | EFI partitions; UEFI + TPM required on Nest |
| Server 2022 | Server unattend sample; same Autounattend + companion pattern |
| Server 2025 | EFI-style layout like Win11; UEFI + TPM |

### Using Windows Answer Files

1. Put an Autounattend Jinja template (and optional companion) in `automation/answerfiles/`, or pull from [Hatchery-Library](https://github.com/dustinestes/Hatchery-Library) (`answerfiles/windows/`).
2. On the Clutch VM: set Guest OS, Admin Username, select the Answer File, fill declared parameters (password is supplied at hatch).
3. Hatch: Controller renders tokens, packs media, Nest attaches; Windows Setup runs unattended; companion prepares remoting; Hatchery provisions scripts until fledged.
4. After fledged: rotate or harden the hatch admin yourself if the guest outlives setup (see [Hatch-scoped through fledged](#hatch-scoped-through-fledged)).

<br>

---

<br>

## Linux

**Planned** ([#217](https://github.com/dustinestes/Hatchery/issues/217)). Not scheduled ahead of Nest remoting MVP.

Expected kinds differ from Windows Autounattend:

- cloud-init NoCloud (`user-data` / `meta-data` on a seed volume)
- kickstart / preseed / autoinstall (distribution-specific)

Answer Files remain the product umbrella; `hatchery.kind` and Nest attach strategy will select the media layout. Do not assume floppy or `Autounattend.xml` filenames.

Admin Username / Password form fields hide for non-Windows Guest OS today (#453). Linux bootstrap identity (SSH keys, etc.) is out of scope until #217.

<br>

---

<br>

## macOS

**Planned / often N/A.** UTM and macOS guests do not use Windows Autounattend. Capability “answer file attach” may be unsupported ([`docs/providers.md`](providers.md)). The Clutch form already hides Answer File and Windows admin fields when the Guest OS is not in the Windows hatch set (#453).

<br>

---

<br>

## Nest attach

Answer File **bytes** are Nest-agnostic. **Attach** is Nest/provider-specific, gated by
`BaseProvider.supports_answer_file_attach` and implemented in
`prepare_answer_file_media` (Nest id → factory; ADR-0003 / #454).

| Nest | Windows attach (status) |
|---|---|
| libvirt local | Floppy image with Autounattend.xml (+ companion) - works today |
| libvirt remote | Planned |
| Hyper-V | Planned - Gen2 often uses a second DVD/ISO, not floppy |
| UTM | Planned / N/A depending on guest |

Hatch (UI and CLI) fails early when a Clutch needs Answer File attach and the selected Nest
reports `supports_answer_file_attach=False`. See the [provider matrix](providers.md). Do not
hard-wire libvirt floppy into operator surfaces.

<br>

---

<br>

## Architecture

Locked decision record: [ADR-0024](adr/0024-answer-files-product-model.md).

```
Hatchery-Library answerfiles/  (optional pull/import)
        │
        ▼
automation/answerfiles/  +  Clutch answer_file + params + admin_*
        │
        ▼
Controller render (Jinja: system tokens + user params)
        │
        ▼
Pack media + companions  →  Nest provider attach  →  guest installer
        │
        ▼
WinRM provision (Scripts) until fledged
```

<br>

---

<br>

## Example files

Optional Windows samples under Hatchery-Library `answerfiles/windows/`:

| File | Role |
|---|---|
| `win10-autounattend.xml.j2` | Win10 Autounattend + system/user tokens |
| `win11-autounattend.xml.j2` | Win11 Autounattend |
| `server2022-autounattend.xml.j2` | Server 2022 Autounattend |
| `server2025-autounattend.xml.j2` | Server 2025 Autounattend |
| `hatchery-setup.ps1` | Shared first-boot companion |

How-to stays in this document. Hatchery-Library does not duplicate operator docs. Pull companions alongside the template (same `automation/answerfiles/` directory).

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
