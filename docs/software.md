<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Software</h1>
<br clear="both">

Post-boot guest application packages - Automations sibling of [Scripts](automations.md) and install-time [Answer Files](answer-files.md).

<br>

## Contents

- [Contents](#contents)
- [Overview](#overview)
- [Software vs Scripts vs Answer Files](#software-vs-scripts-vs-answer-files)
- [Storage and identity](#storage-and-identity)
- [Definition file](#definition-file)
- [Offline payloads](#offline-payloads)
- [Guest path roles](#guest-path-roles)
- [Clutch automations](#clutch-automations)
- [Library](#library)
- [Detection](#detection)
- [Architecture](#architecture)
- [Related](#related)

---

<br>

## Overview

**Software** is Hatchery’s product noun for staging offline installer payloads on a guest and running defined install / uninstall / detect commands as ordered Clutch steps after the guest is reachable.

Product shape is locked in [ADR-0025](adr/0025-software-product-model.md). Inventory, Library domain, hatch provision, and Nest/VM UI land in child issues under [#199](https://github.com/dustinestes/Hatchery/issues/199).

<br>

---

<br>

## Software vs Scripts vs Answer Files

| | Software | Automation Scripts | Answer Files |
|---|---|---|---|
| When | After the guest is reachable (ordered with Scripts) | After the guest is reachable | During OS install / first-boot media |
| Who consumes | Guest shell (WinRM today; SSH later) | Guest shell | Guest **installer** / early boot |
| What | Package definition + optional OS payload tree | Script file under `automation/scripts/` | Template under `automation/answerfiles/` |
| Clutch | `type: software` entry in `automations` | `type: script` entry in `automations` | `answer_file:` / parameters (install-time) |

Scripts remain for cross-cutting guest work. Software hooks (`pre_install` / `post_install`) keep product-specific prep/config with the payload.

<br>

---

<br>

## Storage and identity

Packages live under `automation/software/` in the Hatchery data directory:

```
automation/software/
  Microsoft.VisualStudioCode.1.96.0/     # id = Publisher.Product.Version
    software.yaml
    windows/                            # optional offline payload (OS-scoped)
      VSCodeSetup-x64.exe
    linux/
      ...
```

- **Id / folder name:** `Publisher.Product.Version` - stable Clutch and Nest-cache reference; Library filter `*software/*`
- **Parse rule (folder id only):** split on `.`; segment 0 = publisher key, segment 1 = product key, everything after the second `.` = version string (semver dots allowed)
- **Display:** UI and docs show publisher / product / version from **`software.yaml`**, not by relying on folder parsing
- **Dots in product names:** omit `.` from the product **segment** of the folder id (e.g. folder `Acme.FooBar.1.0.0`, YAML `product: Foo.Bar` as preferred for display)

<br>

---

<br>

## Definition file

Each package directory has a `software.yaml`. Illustrative shape (exact keys in the schema child / ADR):

```yaml
hatchery:
  kind: software
  publisher: Microsoft
  product: VisualStudioCode
  version: "1.96.0"
  architecture: x64
platforms:
  windows:
    pre_install: []          # optional; command and/or script hooks
    install:
      command: '.\VSCodeSetup-x64.exe /VERYSILENT /NORESTART'
      success_exit_codes: [0]
      reboot_after: false
    post_install: []
    uninstall:
      command: '...'
      success_exit_codes: [0]
    detect:
      command: 'powershell -NoProfile -Command "..."'   # exit 0 = present
```

| Key | Meaning |
|---|---|
| `pre_install` / `post_install` | Optional arrays; omit or `[]` = skip |
| Each hook item | Exactly one of `command` (inline) or `script` (relative path under staged payload) |
| Order | Array index order; stop the software step on first non-success exit |
| `success_exit_codes` | Same shape as install (default `[0]` if omitted) |
| cwd | `software_package(id)` (same as install) |

<br>

---

<br>

## Offline payloads

Controller/Nest stores optional `windows/`, `linux/`, `macos/` trees under the package id (may contain multiple files and subdirs). On hatch, Hatchery copies **the entire contents** of the guest’s OS folder (recursive) into the resolved `software_package(id)` path on the guest. It does not create a nested `windows/` on the guest and does not stage sibling OS trees.

Install and hook commands are relative to that per-package staging folder (e.g. `.\Setup.exe …`), never `.\windows\…`.

<br>

---

<br>

## Guest path roles

Path roles are the same tokens in docs, ADR, and code. They resolve from **Clutch Guest OS** (guest plane), never Controller OS, via `guest_paths_for(GuestOS)` (or equivalent).

| Role | Meaning |
|---|---|
| `root` | Hatchery-managed guest root |
| `logs` | First-boot + per-script audit (`Write-HatchEvent`) |
| `temp` | Ephemeral handoff (e.g. setup-complete flag) |
| `software` | Parent of staged installer payloads |
| `software_package(id)` | `{software}/{Publisher.Product.Version}` |

| Role | Windows (locked) | Linux | macOS |
|---|---|---|---|
| `root` | `C:\Program Files\Hatchery` | TBD | TBD |
| `logs` | `{root}\logs` | `{root}/logs` | `{root}/logs` |
| `temp` | `{root}\temp` | `{root}/temp` | `{root}/temp` |
| `software` | `{root}\software` | `{root}/software` | `{root}/software` |
| `software_package(id)` | `{software}\{id}` | `{software}/{id}` | `{software}/{id}` |

Windows values match today’s guest directory in [Orchestration](orchestration.md#hatchery-guest-directory). Linux/macOS absolute `root` values land when those guests are supported; until then the resolver raises a clear unsupported error.

Windows example after staging `Microsoft.VisualStudioCode.1.96.0`:

```
C:\Program Files\Hatchery\software\Microsoft.VisualStudioCode.1.96.0\
  VSCodeSetup-x64.exe
  (any other files that were under automation/software/…/windows/)
```

<br>

---

<br>

## Clutch automations

One ordered post-boot list. **Every entry declares `type`** (`script` or `software`). Bare string script names are not accepted (pre-release migration: edit Clutches once).

```yaml
automations:
  - type: script
    name: configure-vm-basics-windows.ps1
  - type: software
    name: Microsoft.VisualStudioCode.1.96.0
    reboot_after: false
    clean_payload_on_success: true
  - type: script
    name: enable-rdp-windows.ps1
    reboot_after: true
```

| Field | `script` | `software` |
|---|---|---|
| `type` | required | required |
| `name` | script basename under `automation/scripts/` | package id under `automation/software/` |
| `reboot_after` | yes | yes |
| `parameters` | yes (existing) | no (v1) |
| `clean_payload_on_success` | n/a | yes (default true) - remove `software_package(id)` after install OK |

Hatch lifecycle: `script` → today’s script runner; `software` → stage payload → `pre_install` → `install` → `post_install` → reboot/exit → optional clean.

<br>

---

<br>

## Library

Library domain **`software`** (migrated from reserved `packages`). Fresh Controllers seed an **All Software** binding (`filter: *software/*`). Hatchery-Library remains a content source only; pull is operator-driven. Sample packages under `software/` land in a child issue (Windows first).

<br>

---

<br>

## Detection

Detection runs the platform `detect.command` over Controller/Nest remoting (WinRM today; SSH later). Exit 0 means present. There is no in-guest agent daemon and no guest login UI requirement for detect. Hatch skip-if-present and Nest/VM present/missing UI land in child issues.

<br>

---

<br>

## Architecture

```
Clutch ordered automations
  → type: script  → provision.run_script
  → type: software
       → load software.yaml
       → copy OS-dir contents → software_package(id)
       → pre_install[] → install → post_install[]
       → optional remove software_package(id)
       → detect (status / skip-if-present)
```

Nest cache gains an `automation/software` artifact kind for definition + selected OS payload tree. Guest paths always go through the role map above.

<br>

---

<br>

## Related

- [ADR-0025](adr/0025-software-product-model.md) - Software product model
- [Automations (Scripts)](automations.md) - post-boot scripts
- [Answer Files](answer-files.md) - install-time templates
- [Library](library.md) - pull / bindings
- [Orchestration](orchestration.md) - hatch lifecycle and guest directory
- Epic [#199](https://github.com/dustinestes/Hatchery/issues/199)

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
