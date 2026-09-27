# ADR-0024: Answer Files product model

- **Status:** Accepted
- **Date:** 2026-09-26
- **Issues:** [#447](https://github.com/dustinestes/Hatchery/issues/447) (this ADR + operator docs); inventory [#177](https://github.com/dustinestes/Hatchery/issues/177); Library consume-only [ADR-0011](0011-library-consume-only-no-clutch-roundtrip.md); Nest factory [ADR-0003](0003-nest-registry-provider-factory.md)

## Context

Hatchery today has two overlapping paths for Windows unattended install:

1. **Shadow Jinja** - when admin credentials are present, the Controller silently renders Autounattend XML (and `hatchery-setup.ps1`) from [`templates/answerfiles/`](../../templates/answerfiles/) and attaches a floppy on libvirt ([`lib/providers/libvirt.py`](../../lib/providers/libvirt.py)).
2. **Optional `os_config`** - a file under `automation/os_config/` used only when admin credentials are absent.

That naming (`os_config`) sits next to post-boot **Scripts** and reads like Settings. The blind path is not Nest- or OS-agnostic (Hyper-V Gen2 often has no floppy; Linux cloud-init needs different media layout). Operators cannot inspect, Library-sync, or parameterize install templates the way they do Scripts. Expanding to multi-Nest / multi-guest requires a clear install-time artifact model that is not guest-plane WinRM.

## Decision

1. **Product name:** **Answer Files** (nav, docs, UI). Not “OS Config.”
2. **Data directory:** `automation/answerfiles/` (rename from `automation/os_config/`). One-time migrate when the rename issue lands.
3. **Library domain:** `answerfiles` (peer of `scripts` / `clutches` / `media`). Fresh Controllers seed the Hatchery Library forge connection with an `answerfiles` kind and **All Answer Files** binding (`filter: *answerfiles/*`, so catalog hits stay under the Library repo’s `answerfiles/` tree including Jinja templates and companions). **Do not** auto-pull sample bytes into the operator data dir - pull remains operator-driven (ADR-0011). Hatchery-Library remains a content source only (no how-to docs in that repo).
4. **Clutch fields:** `answer_file:` (filename under `automation/answerfiles/`) and `answer_file_parameters:` (map). Load-time alias from legacy `os_config` until rename ships. Precedence: selected `answer_file` is required for guests that support answer-file attach; admin credentials do **not** select a hidden Controller template.
5. **Credentials (2A):** Keep **Admin Username / Password** on the Clutch VM when Guest OS needs them for hatch through fledged. Inject as **reserved system tokens** (`vm_name`, `admin_username`, `admin_password`). Hide or disable by Guest OS when not applicable. Creds are hatch-scoped through fledged; post-fledged rotation is operator/Library scripts, not a product dependency on stored admin forever.
6. **Templates:** User-owned files in the data dir (and optional Library pull). **No** silent shadow render from Controller `templates/answerfiles/*.j2` as the product path once Library samples exist and hatch render is switched (hard gate: do not delete Controller templates until samples are merged and reviewed). Implemented in [#452](https://github.com/dustinestes/Hatchery/issues/452): shadow templates removed; Windows hatch requires `answer_file`.
7. **Parameters:** Declared in the answer file (YAML frontmatter under a `hatchery:` header). Not PowerShell-style introspection. Substitution via Jinja `{{ name }}`. User-declared param names must not collide with reserved system tokens.
8. **Companions:** Frontmatter may list companion files (e.g. `hatchery-setup.ps1`) packed onto the same attach media. Companions live under `automation/answerfiles/`. The FirstLogonCommands → companion contract is documented, not hard-coded product magic outside the user’s file.
9. **Attach:** Nest/provider responsibility (floppy vs seed ISO vs Hyper-V DVD), capability-flagged via the Nest factory. Libvirt Windows floppy remains the first working backend. Do not bake “floppy” into the product noun.
10. **Guest control plane:** Not a prerequisite. Install-time attach is Nest work; guest WinRM remains provision ([`lib/provision.py`](../../lib/provision.py)).

### Sample contract (Hatchery-Library)

Optional Windows samples (content only) under `answerfiles/windows/` in [Hatchery-Library](https://github.com/dustinestes/Hatchery-Library), ported from Controller Jinja with frontmatter, reserved system tokens, locale user params, and shared `hatchery-setup.ps1` companion. Operators pull or import if they want examples. Operator how-to: [`docs/answer-files.md`](../answer-files.md).

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
---
```

Exact frontmatter keys are finalized in the declared-params implementation issue; samples follow this shape.

## Consequences

- Scripts remain post-boot; Answer Files remain install-time. Same UX *shape* (pick file, fill fields), different engine and Nest role.
- Clutch / hatch UX becomes honest: operators see and own the unattend template.
- Multi-Nest attach strategies can diverge without changing the Answer File product noun.
- Shadow Jinja removed in [#452](https://github.com/dustinestes/Hatchery/issues/452); Windows hatch requires a user Answer File (Library samples under `answerfiles/windows/`).
- Linux (#217) and macOS/UTM stay capability stubs until Nest attach strategies exist.
- Rename and Library domain work are separate small PRs; this ADR locks the target shape.

## Non-goals

- In-app XML/YAML editor for answer files
- Guest-plane “re-apply answer file” after install
- Auto-seeding answer file bytes into the operator data dir
- Linux seed / kickstart / preseed recipes in the first attach slice
- Encrypting hatch passwords ([#110](https://github.com/dustinestes/Hatchery/issues/110))

## Alternatives

| Option | Why not |
|---|---|
| Keep shadow Jinja as primary path | Invisible, libvirt-centric, not Library-friendly |
| Free-form admin only as answer-file params (2B) | Breaks stable hatch→fledged WinRM without extra role metadata |
| Name remains `os_config` | Conflates with Scripts / Settings |
| Document how-to in Hatchery-Library | Library is consume-only content; Hatchery owns operator docs |

## Related docs

- Operator how-to: [`docs/answer-files.md`](../answer-files.md)
- Scripts (post-boot): [`docs/automations.md`](../automations.md)
- Provider matrix: [`docs/providers.md`](../providers.md)
- Orchestration: [`docs/orchestration.md`](../orchestration.md)
