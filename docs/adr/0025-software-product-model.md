# ADR-0025: Software product model

- **Status:** Accepted
- **Date:** 2026-09-27
- **Issues:** [#199](https://github.com/dustinestes/Hatchery/issues/199) (this ADR + operator docs); inventory Import [#469](https://github.com/dustinestes/Hatchery/issues/469); Library domain [#470](https://github.com/dustinestes/Hatchery/issues/470); Artifactory Software ingest (post-v1) [#487](https://github.com/dustinestes/Hatchery/issues/487); Library consume-only [ADR-0011](0011-library-consume-only-no-clutch-roundtrip.md); Nest factory [ADR-0003](0003-nest-registry-provider-factory.md); Controller package distribution [ADR-0005](0005-controller-only-package-distribution.md) (orthogonal)

## Context

Hatchery Automations today are post-boot **Scripts** under `automation/scripts/` plus install-time **Answer Files**. Operators also need a first-class way to stage and run **guest application installers** (offline payloads + detect/install/uninstall) as ordered Clutch steps alongside Scripts - without inventing a public package registry or conflating this with Controller OS package-manager distribution (ADR-0005).

A reserved Library connection kind `packages` exists but is empty and ambiguous next to “OS packages.” The product needs a clear Automations noun, on-disk layout, Library domain, Clutch serialization, and guest path vocabulary that works when Linux/macOS guests land later.

## Decision

1. **Product name:** **Software** (Automations sibling of Scripts / Answer Files). Ambiguous UI noun “packages” stays out of primary copy.
2. **Data directory:** `automation/software/`. Each package is a directory whose name is the stable id.
3. **Identity:** Folder id = `Publisher.Product.Version`. Parse rule (folder id only): split on `.`; segment 0 = publisher key, segment 1 = product key, **everything after the second `.` = version string** (semver dots allowed). **Display** labels come from `software.yaml` (authoritative). Product dots in the folder id are omitted (outlier); do not invent a second delimiter in v1.
4. **Definition file:** `software.yaml` in each package dir. Metadata under `hatchery` (no architecture field). Lifecycle under `platforms.{os}.{arch}` where OS ∈ `windows` \| `linux` \| `macos` and arch ∈ `x86` \| `x64` \| `arm64` \| `any`. Each arch unit has `install` / `uninstall` / `detect` plus optional `pre_install` / `post_install` hook arrays. Each hook item is exactly one of `command` (inline) or `script` (relative path under the staged payload); run in array order; stop on first non-success exit. `success_exit_codes` defaults to `[0]` when omitted. **`any` is exclusive** under an OS: if present, no other arch keys under that OS (reject at load time - do not mix or ignore). Single-arch packages list one arch key. Authoritative schema: [`lib/software.py`](../../lib/software.py) ([#471](https://github.com/dustinestes/Hatchery/issues/471)); operator how-to: [`docs/software.md`](../software.md).
5. **Offline payloads:** Optional trees `{os}/{arch}/…` under the package id (mirrors YAML). On hatch, copy **only** the guest OS + selected arch subtree (guest arch → `x86`/`x64`/`arm64`, else `any` if that unit exists) into the guest `software_package(id)` path. Do **not** nest `windows/` or arch folders on the guest; do not stage sibling OS or arch trees. Install/hook commands are relative to that staging folder.
6. **Library domain:** `software`. Migrate connection kind / CHECK `packages` → `software`; seed **All Software** binding (`filter: *software/*`) like Answer Files. Fresh Controllers get the kind + binding; pull remains operator-driven (ADR-0011).
7. **Clutch automations:** One ordered post-boot list. **Every entry declares `type: script` or `type: software`** (required). No bare-string script shorthand (pre-release break; document migration). Software rows support `reboot_after` and `clean_payload_on_success` (default true). Scripts keep `reboot_after` (+ existing parameters); Software has no parameters map in v1.
8. **Detection:** Controller/Nest remoting runs the defined detect command (WinRM today; SSH later) - not an in-guest agent daemon. Guest-plane login UI is not required for detect.
9. **Guest path roles:** One vocabulary resolved per **guest OS family** via `guest_paths_for(GuestOS)` (never Controller `sys.platform`):

| Role | Meaning |
|---|---|
| `root` | Hatchery-managed guest root |
| `logs` | First-boot + per-script audit |
| `temp` | Ephemeral handoff |
| `software` | Parent of staged installer payloads |
| `software_package(id)` | `{software}/{Publisher.Product.Version}` |

| Role | Windows (locked) | Linux | macOS |
|---|---|---|---|
| `root` | `C:\Program Files\Hatchery` | TBD | TBD |
| `logs` | `{root}\logs` | `{root}/logs` | `{root}/logs` |
| `temp` | `{root}\temp` | `{root}/temp` | `{root}/temp` |
| `software` | `{root}\software` | `{root}/software` | `{root}/software` |
| `software_package(id)` | `{software}\{id}` | `{software}/{id}` | `{software}/{id}` |

Today’s strings in [`lib/provision.py`](../../lib/provision.py) (`HATCHERY_GUEST_DIR`, setup flag/log paths) are the **Windows** row. Linux/macOS raise a clear unsupported error until values are filled. New provision/software code must use the role map, not hard-coded Windows paths. Reserved guest path env vars (so packages need not hardcode log paths): [ADR-0026](0026-guest-clutch-environment.md) / [#501](https://github.com/dustinestes/Hatchery/issues/501).

10. **Hatch walk:** For `type: software`: load definition → resolve OS + arch unit → **detect (skip-if-present)** → else stage that `{os}/{arch}/` payload → run `pre_install[]` → `install` → `post_install[]` → **detect (verify)** → honor reboot/exit → optionally remove `software_package(id)` when `clean_payload_on_success` (and something was staged). Nest cache gains an `automation/software` artifact kind. Transfer/pre-stage details track with offline staging / [#131](https://github.com/dustinestes/Hatchery/issues/131). Skip-if-present: [#502](https://github.com/dustinestes/Hatchery/issues/502).
11. **One content shape:** Library forge/path sources, Hatchery-Library samples, operator cache, and Inventory Import all use **expanded package directories** (`software/{Publisher.Product.Version}/` with immediate `software.yaml`). **No zip** (or other archive) as SoR, Inventory Import format, or forge/Library sample format.
12. **Inventory Import:** One directory picker. Classify: package root (immediate `software.yaml`) → import that id; parent of one or more package roots → batch; otherwise reject (including selecting `windows/` / `x64/` alone). Package id = folder name; create-only. Do not auto-walk up from an OS or arch child. Operators may also place dirs under `automation/software/` without Import.
13. **Library pull (forge/path):** Catalog and pull **package units** (not leaf-only). Copy the whole tree into `automation/software/{id}/`. Prefer one provenance row per package id. Artifactory (`type: api`) may later ingest **dir trees or single archives** but must **normalize into the same cache dirs** ([#487](https://github.com/dustinestes/Hatchery/issues/487)); that is not a second Software shape.

### Illustrative `software.yaml`

```yaml
hatchery:
  kind: software
  publisher: Microsoft
  product: VisualStudioCode
  version: "1.96.0"
platforms:
  windows:
    x64:
      pre_install:
        - command: 'powershell -NoProfile -Command "..."'
          success_exit_codes: [0]
        - script: '.\hooks\pre-install.ps1'
          success_exit_codes: [0]
      install:
        command: '.\VSCodeSetup-x64.exe /VERYSILENT /NORESTART'
        success_exit_codes: [0]
        reboot_after: false
      post_install:
        - script: '.\hooks\post-install.ps1'
          success_exit_codes: [0]
      uninstall:
        command: '...'
        success_exit_codes: [0]
      detect:
        command: 'powershell -NoProfile -Command "..."'   # exit 0 = present
```

Payload tree for that unit: `windows/x64/…` under the package id (sibling arches optional).

### Illustrative Clutch `automations`

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

Exact keys are finalized in the definition-schema and Clutch-form children; samples follow this shape.

## Consequences

- Automations gain three peers: Scripts, Software, Answer Files - distinct engines, shared UX *shape* where it helps (pick + order).
- Library kind rename removes the empty `packages` slot; docs and CLI use `software`.
- Pre-release Clutches that used bare script name strings must be edited once; no long-lived alias.
- Guest path roles unlock Linux/macOS guests without rewriting Software install tokens later.
- Implementation is child issues under [#199](https://github.com/dustinestes/Hatchery/issues/199); this ADR locks the target shape only (no inventory/Library/Clutch code in the ADR PR).

## Non-goals (v1)

- Full dependency solver / public Hatchery package registry
- Replacing Scripts
- FoD / Windows Update capability sourcing
- Merging Controller OS package-manager distribution (ADR-0005) with this product noun
- In-app `software.yaml` editor (tracked as optional / post-v1; likely wont-do unless reopened)
- Guest-plane login UI solely for Software detect
- Zip (or other archive) as Library/forge/Hatchery-Library SoR, operator-cache layout, or Inventory Import
- Settings “source shape” fork of Software (Artifactory archive ingest stays adapter-side, post-v1 #487)

## Alternatives

| Option | Why not |
|---|---|
| Keep Library kind `packages` | Ambiguous vs OS packages / ADR-0005; empty reserved slot |
| Product noun “Packages” in Automations | Same ambiguity in primary UI |
| Bare-string Clutch script entries forever | Blocks a single typed parse path for mixed Scripts + Software |
| In-guest agent for detect | Heavier than remoting the defined detect command |
| Document how-to only in Hatchery-Library | Library is consume-only content; Hatchery owns operator docs |
| Zip as Library / Import SoR | Forces unpack before YAML/sync; second shape vs forge/path dirs; Inventory browser cannot attach siblings to a lone file pick |
| Per-connection Software “source shape” in Settings | Forks the product noun; adapters should normalize into cache dirs instead |

## Related docs

- Operator how-to: [`docs/software.md`](../software.md)
- Scripts (post-boot): [`docs/automations.md`](../automations.md)
- Answer Files (install-time): [`docs/answer-files.md`](../answer-files.md)
- Library: [`docs/library.md`](../library.md)
- Orchestration (guest directory): [`docs/orchestration.md`](../orchestration.md)
