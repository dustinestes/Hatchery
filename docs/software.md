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
- [Online / command-only packages](#online--command-only-packages)
- [Guest path roles](#guest-path-roles)
- [Clutch automations](#clutch-automations)
- [Library](#library)
- [Detection](#detection)
- [Architecture](#architecture)
- [Related](#related)

---

<br>

## Overview

**Software** is Hatchery’s product noun for running defined install / uninstall / detect commands as ordered Clutch steps after the guest is reachable. Packages may stage **optional** offline installer payloads, or be **YAML-only** (online / command-only): the guest downloads an installer or calls a package manager such as winget.

Product shape is locked in [ADR-0025](adr/0025-software-product-model.md) and [ADR-0033](adr/0033-software-online-command-only.md). Inventory, Library domain, hatch provision, and Nest/VM UI land in child issues under [#199](https://github.com/dustinestes/Hatchery/issues/199).

<br>

---

<br>

## Software vs Scripts vs Answer Files

| | Software | Automation Scripts | Answer Files |
|---|---|---|---|
| When | After the guest is reachable (ordered with Scripts) | After the guest is reachable | During OS install / first-boot media |
| Who consumes | Guest shell (SSH primary; WinRM Windows fallback) | Guest shell | Guest **installer** / early boot |
| What | Package definition + optional OS payload tree (or YAML-only online install) | Script file under `automation/scripts/` | Template under `automation/answerfiles/` |
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

### Inventory (Controller UI)

**Automations → Software** lists package directories under `automation/software/`. Operators can:

- **Import** via a **directory picker** (same layout as Library / disk):
  - Select a **package folder** that contains `software.yaml` at its root, or
  - Select a **parent folder** of one or more such packages (batch import)
  - Do **not** select `windows/`, `linux/`, or `macos/` alone
  - Package id = folder name (`Publisher.Product.Version`); create-only (refuse overwrite)
- **Delete** a package tree
- Inspect `software.yaml` in the detail pane (metadata from YAML when present)

Operators may also place package dirs under `automation/software/` without Import. Library pull for domain `software` (forge/path package trees) lands in [#470](https://github.com/dustinestes/Hatchery/issues/470). Artifactory archive/dir normalize into the same cache dirs is post-v1 [#487](https://github.com/dustinestes/Hatchery/issues/487). **No zip Import.**

<br>

---

<br>

## Definition file

Each package directory has a `software.yaml`. Locked shape ([#471](https://github.com/dustinestes/Hatchery/issues/471) / [ADR-0025](adr/0025-software-product-model.md)):

```yaml
hatchery:
  kind: software
  publisher: Microsoft
  product: VisualStudioCode
  version: "1.96.0"
platforms:
  windows:                   # windows | linux | macos (at least one OS required)
    x64:                     # x86 | x64 | arm64 | any (at least one arch per OS)
      pre_install: []        # optional; omit or [] = skip
      install:
        command: '.\VSCodeSetup-x64.exe /VERYSILENT /NORESTART'
        success_exit_codes: [0]   # optional; default [0]
        reboot_after: false       # optional; default false
      post_install: []
      uninstall:
        command: '...'
        success_exit_codes: [0]
      detect:
        # Inline PowerShell (not nested powershell -Command). Exit 0 = present.
        # Typical Win32 ARP: Publisher + DisplayName + DisplayVersion under Uninstall.
        command: |
          $pub='Microsoft'; $name='Visual Studio Code'; $ver='1.96.0'
          foreach ($root in @(
            'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
          )) {
            Get-ChildItem $root -ErrorAction SilentlyContinue | ForEach-Object {
              $i = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
              if ($i.Publisher -like $pub -and $i.DisplayName -like $name -and "$($i.DisplayVersion)" -eq $ver) {
                exit 0
              }
            }
          }
          exit 1
```

| Key | Meaning |
|---|---|
| `hatchery.kind` | Must be `software` |
| `hatchery.publisher` / `product` / `version` | Required non-empty display fields |
| `platforms` | Mapping of OS → arch → unit; at least one OS required |
| Arch keys | `x86`, `x64`, `arm64`, or `any` only. Single-arch packages list one key |
| `any` | Arch-agnostic / multi-arch installer unit. **If `any` is present under an OS, no other arch keys are allowed under that OS** (rejected at load time) |
| `pre_install` / `post_install` | Optional arrays; omit or `[]` = skip |
| Each hook item | Exactly one of `command` (inline) or `script` (relative path under staged payload) |
| `install` / `uninstall` / `detect` | Required per arch unit; `command` required and non-empty |
| `success_exit_codes` | Default `[0]` when omitted; must not be empty when present |
| `install.reboot_after` | Optional bool; default `false` |
| Order | Hook array index order; stop the software step on first non-success exit |
| cwd | `software_package(id)` (same as install) |
| Runner | Hatchery sets reserved + Clutch user env, sets cwd, runs the authored `command`/`script`, waits for exit. No installer-specific rewriting. Env contract: [ADR-0026](adr/0026-guest-clutch-environment.md) / [#501](https://github.com/dustinestes/Hatchery/issues/501) |

There is **no** `hatchery.architecture` field. Unknown top-level, OS, or arch keys are rejected. Inventory and the package content API surface load-time validation errors without failing the rail list (missing/invalid YAML still appears as a package).

<br>

---

<br>

## Offline payloads

Offline installer trees under `platforms/{os}/{arch}/` are staged into the guest
`software_package(id)` directory before install hooks run.

**Windows:** When Guest transport resolves to SSH, Hatchery stages via SCP
(SHA-256 verified). WinRM fallback streams each file over WinRM stdin (not
`-EncodedCommand` payload bytes): before staging it raises guest
`MaxEnvelopeSizekb` to at least 8192 when lower, invokes `powershell.exe` with
`WINRS_SKIP_CMD_SHELL`, and verifies SHA-256 after transfer. Prefer SSH for
large offline trees; do not rely on 1 KiB EncodedCommand append as a product path.

Install and hook commands run with cwd = that per-package staging folder (e.g. `.\Setup.exe …`), never `.\windows\x64\…`. On Windows, prefer bare `msiexec.exe …` over `Start-Process -Wait` under WinRM (filtered admin tokens can hang). Authors may log with MSI `/l*v $env:HATCHERY_SOFTWARE_LOG` and resolve payload files under `$env:HATCHERY_SOFTWARE_PACKAGE` ([ADR-0026](adr/0026-guest-clutch-environment.md)). Hatchery does not wrap msiexec in the Controller.

**Windows UAC (lab/dev posture):** Guest transport runs Software `install.command` via `run_ps` as the hatch admin with no elevated/SYSTEM wrapper. Default UAC can make silent MSI installs exit 0 without product registration. Library `hatchery-setup-windows.ps1` therefore sets UAC to Never notify at first boot ([#543](https://github.com/dustinestes/Hatchery/issues/543)); that is weaker than the Windows default slider and is intentional for reliable silent installs. `LocalAccountTokenFilterPolicy` is unrelated (WinRM token filter only). `hatchery-cleanup-windows.ps1` restores prior/default UAC when operators run cleanup. See [orchestration - first-boot steps](orchestration.md#the-orchestrator-script-hatchery-setup-windowsps1).

Controller/Nest stores optional `{os}/{arch}/` trees under the package id (mirrors `platforms` in `software.yaml`). Example:

```text
automation/software/Microsoft.VisualStudioCode.1.96.0/
  software.yaml
  windows/
    x64/
      VSCodeSetup-x64.exe
      hooks/
```

On hatch, Hatchery copies **only** the guest OS + selected arch subtree (guest arch, or `any` when that unit exists) into the resolved `software_package(id)` path. It does not create nested `windows/` or `x64/` on the guest and does not stage sibling OS or arch trees.

<br>

---

<br>

## Online / command-only packages

When a package has no `{os}/{arch}/` payload directory, Hatchery still loads `software.yaml`, resolves the guest OS + arch unit, runs detect (skip-if-present), and runs `install.command` with **zero files staged**. That is the **online / command-only** shape ([ADR-0033](adr/0033-software-online-command-only.md) / [#561](https://github.com/dustinestes/Hatchery/issues/561)).

| Still required | Not required |
|---|---|
| `platforms.{os}.{arch}` with install / uninstall / detect | Shipping binaries under `{os}/{arch}/` |
| Per-OS command text (PowerShell, bash, winget, apt, …) | Controller download into the Software cache |
| Guest outbound HTTPS and/or guest package manager when the command needs them | Baking winget into `hatchery-setup-windows.ps1` |

Typical patterns (URLs and package ids live inside the authored command, not a `source:` schema key):

1. **HTTPS download + install** - guest `Invoke-WebRequest` (or equivalent) to a known installer URL, then silent EXE/MSI switches.
2. **Guest package manager** - e.g. `winget install -e --id … --silent --accept-package-agreements --accept-source-agreements` (QEMU Guest Agent, VirtIO guest tools).
3. **Opt-in tool bootstrap** - a separate Software package that installs App Installer / winget via HTTPS when the image lacks it; place it **before** winget-based rows in Clutch `automations`.

Hatchery-Library samples for these shapes are YAML-only living packages (including post-install VirtIO without an attached ISO); the Library README keeps a short shapes sketch. Full contract stays in this doc. Attaching VirtIO media at hatch remains preferred when Windows Setup must load `viostor` during install.

Guest internet, TLS, and UAC/driver silent-install caveats are the same class of operator concern as offline Software ([#543](https://github.com/dustinestes/Hatchery/issues/543) UAC lab posture). Some driver installers (for example SPICE Guest Tools) document Local System for fully silent driver approval; hatch admin remoting may still need lab validation.

<br>

---

<br>

## Guest path roles

Path roles are the same tokens in docs, ADR, and code. They resolve from **Clutch Guest OS** (guest plane), never Controller OS, via `guest_paths_for(GuestOS)` (or equivalent).

| Role | Meaning | Env var |
|---|---|---|
| `root` | Hatchery-managed guest root | `HATCHERY_ROOT` |
| `logs` | First-boot + per-script audit (`Write-HatchEvent`) | `HATCHERY_LOGS` |
| `temp` | Ephemeral handoff (e.g. setup-complete flag) | `HATCHERY_TEMP` |
| `software` | Parent of staged installer payloads | `HATCHERY_SOFTWARE` |
| `modules` | PowerShell modules (`Hatchery` module) | `HATCHERY_MODULES` |
| `software_package(id)` | `{software}/{Publisher.Product.Version}` | `HATCHERY_SOFTWARE_PACKAGE` (Software jobs) |
| per-package installer log | `{logs}/software/{id}.log` | `HATCHERY_SOFTWARE_LOG` (Software jobs) |

| Role | Windows (locked) | Linux | macOS |
|---|---|---|---|
| `root` | `C:\Program Files\Hatchery` | TBD | TBD |
| `logs` | `{root}\logs` | `{root}/logs` | `{root}/logs` |
| `temp` | `{root}\temp` | `{root}/temp` | `{root}/temp` |
| `software` | `{root}\software` | `{root}/software` | `{root}/software` |
| `modules` | `{root}\modules` | `{root}/modules` | `{root}/modules` |
| `software_package(id)` | `{software}\{id}` | `{software}/{id}` | `{software}/{id}` |

Windows values match today’s guest directory in [Orchestration](orchestration.md#hatchery-guest-directory). Linux/macOS absolute `root` values land when those guests are supported; until then the resolver raises a clear unsupported error.

**Env + ensure ([ADR-0026](adr/0026-guest-clutch-environment.md) / [ADR-0032](adr/0032-guest-environment-ensure-job.md)):** Hatchery sets the reserved vars (plus optional Clutch `environment:` user entries) for Script and Software remoting in an outer process scope. Reserved base vars (including `HATCHERY_MODULES`) and a Machine `PSModulePath` append persist on Windows inside the guest environment ensure job before automations; software-scoped package vars stay job-only. Names are identical on every guest OS; values come from `guest_paths_for(GuestOS)` (never Controller OS). Windows units use `$env:NAME`; future POSIX units use `$NAME` / `export`. User keys must not collide with reserved `HATCHERY_*` names or Hatchery-managed `PSModulePath`.

Windows example after staging `Microsoft.VisualStudioCode.1.96.0` (guest arch `x64`):

```
C:\Program Files\Hatchery\software\Microsoft.VisualStudioCode.1.96.0\
  VSCodeSetup-x64.exe
  (any other files that were under automation/software/…/windows/x64/)
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

Hatch lifecycle: `script` → today’s script runner; `software` → detect (skip-if-present) → else stage → `pre_install` → `install` → `post_install` → `detect` (verify) → reboot/exit → optional clean when staged.

<br>

---

<br>

## Library

Library domain **`software`** (migrated from reserved `packages`). Fresh Controllers seed an **All Software** binding (`filter: *software/*`). Hatchery-Library remains a content source only; pull is operator-driven. Samples are **expanded directories** under `software/` (not zip). Catalog/pull treat each package dir as one unit. Artifactory may later deliver trees or archives but still lands cache dirs ([#487](https://github.com/dustinestes/Hatchery/issues/487)).

<br>

---

<br>

## Detection

Detection runs the platform `detect.command` over Guest transport (SSH primary; WinRM Windows fallback) with the same slim contract as install (authored snippet; exit 0 = present). Prefer compact ARP scans (Publisher + DisplayName + DisplayVersion) over ProductCode-only checks when the product writes standard Uninstall keys.

**Skip-if-present ([#502](https://github.com/dustinestes/Hatchery/issues/502)):** hatch runs detect **before** staging. If present, the step succeeds without payload transfer or install. If absent, Hatchery stages, installs, then runs detect again to verify. Pre-detect does not require the package staging directory to exist (registry/ARP detects). Nest/VM present/missing UI status rails land in [#477](https://github.com/dustinestes/Hatchery/issues/477). There is no in-guest agent daemon and no guest login UI requirement for detect.

<br>

---

<br>

## Architecture

```
Clutch ordered automations
  → type: script  → provision.run_script
  → type: software
       → load software.yaml
       → detect (skip-if-present; no stage if already present)
       → else stage platforms/{os}/{arch}/ → software_package(id)
         (skip staging when payload dir missing: online / command-only)
       → pre_install[] → install → post_install[]
       → detect (verify present after install)
       → optional remove software_package(id) when staged (#474)
```

Nest cache gains an `automation/software` artifact kind for definition + selected OS payload tree (tree may be definition-only). Guest paths always go through the role map above.

<br>

---

<br>

## Related

- [ADR-0025](adr/0025-software-product-model.md) - Software product model
- [ADR-0033](adr/0033-software-online-command-only.md) - Online / command-only packages
- [Automations (Scripts)](automations.md) - post-boot scripts
- [Answer Files](answer-files.md) - install-time templates
- [Library](library.md) - pull / bindings
- [Orchestration](orchestration.md) - hatch lifecycle and guest directory
- Epic [#199](https://github.com/dustinestes/Hatchery/issues/199)
- YAML-only Library examples [#561](https://github.com/dustinestes/Hatchery/issues/561)

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
