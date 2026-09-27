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

Product shape is locked in [ADR-0024](adr/0024-answer-files-product-model.md). Today the Controller may still auto-render Windows Autounattend from built-in Jinja when admin credentials are set; that shadow path is being replaced by user-owned Answer Files (see follow-on issues on [#447](https://github.com/dustinestes/Hatchery/issues/447)). Do not delete Controller templates until Hatchery-Library samples are in place.

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

- Place files in `automation/answerfiles/` (Import on Automations → Answer Files, or drop files there on the Controller). Library pull for the `answerfiles` domain is live: bind a path under Library → Connections and pull from Library → Content Available (or `hatchery library content pull --domain answerfiles`).
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
| `admin_password` | Admin password supplied at hatch (not stored long-term as a manage credential) |

Admin username / password remain first-class VM fields when the selected Guest OS needs them for hatch through fledged. Hide them in the form when the OS does not apply. After fledged, rotating that account is an operator/script concern (see Library hardening/cleanup scripts), not something Hatchery must keep using.

### User-declared parameters

Declared in YAML frontmatter under `hatchery.parameters` (exact schema lands with the params implementation). Shown on the Clutch builder like script parameters. Example: locales (`input_locale`, `system_locale`, `ui_language`, `user_locale`).

Substitution uses Jinja: `{{ input_locale }}` in the template body.

Illustrative frontmatter:

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
| `answer_file_parameters` | Map of user-declared param values for that file (follow-on) |
| `admin_username` / hatch password | Feed system tokens when the Guest OS needs them |

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

1. Put an Autounattend Jinja template (and optional companion) in `automation/answerfiles/`, or pull from Hatchery-Library when available.
2. On the Clutch VM: set Guest OS, Admin Username / Password, select the Answer File, fill declared parameters.
3. Hatch: Controller renders tokens, packs media, Nest attaches; Windows Setup runs unattended; companion prepares remoting; Hatchery provisions scripts until fledged.

<br>

---

<br>

## Linux

**Planned** ([#217](https://github.com/dustinestes/Hatchery/issues/217)). Not scheduled ahead of Nest remoting MVP.

Expected kinds differ from Windows Autounattend:

- cloud-init NoCloud (`user-data` / `meta-data` on a seed volume)
- kickstart / preseed / autoinstall (distribution-specific)

Answer Files remain the product umbrella; `hatchery.kind` and Nest attach strategy will select the media layout. Do not assume floppy or `Autounattend.xml` filenames.

Admin Username / Password form fields will hide or change when Linux guests need SSH keys or other bootstrap identity instead.

<br>

---

<br>

## macOS

**Planned / often N/A.** UTM and macOS guests do not use Windows Autounattend. Capability “answer file attach” may be unsupported ([`docs/providers.md`](providers.md)). The Clutch form should hide Answer File and Windows admin fields when the Guest OS cannot use them.

<br>

---

<br>

## Nest attach

Answer File **bytes** are Nest-agnostic. **Attach** is Nest/provider-specific:

| Nest | Windows attach (status) |
|---|---|
| libvirt local | Floppy image with Autounattend.xml (+ companion) - works today |
| libvirt remote | Planned |
| Hyper-V | Planned - Gen2 often uses a second DVD/ISO, not floppy |
| UTM | Planned / N/A depending on guest |

See the [provider matrix](providers.md). UI and CLI must go through Nest id → factory; do not hard-wire libvirt floppy into operator surfaces.

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

Optional Windows samples (when published under Hatchery-Library `answerfiles/windows/`):

| File | Role |
|---|---|
| `win10-autounattend.xml.j2` | Win10 Autounattend + system/user tokens |
| `win11-autounattend.xml.j2` | Win11 Autounattend |
| `server2022-autounattend.xml.j2` | Server 2022 Autounattend |
| `server2025-autounattend.xml.j2` | Server 2025 Autounattend |
| `hatchery-setup.ps1` | Shared first-boot companion |

How-to stays in this document. Hatchery-Library does not duplicate operator docs.

Until samples land and hatch switches to user Answer Files, Controller shadow templates under `templates/answerfiles/` still drive the auto-render path when admin credentials are set. See [orchestration](orchestration.md).

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
