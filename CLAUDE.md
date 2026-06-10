# Hatchery

A local web application for creating, provisioning, and managing VMs on an Ubuntu host using QEMU/KVM (libvirt / Virtual Machine Manager). Built Windows-first in v1, with an architecture designed to support any guest OS on KVM and remote management of Hyper-V VMs in future versions.

## Origin and Context

Designed for a developer who works on an Ubuntu host and needs Windows guest VMs (Win10, Win11, Server 2022, Server 2025) for development targeting Windows environments. The goal is full automation: create a VM, run an unattended Windows install, provision dev tools, and have a ready environment — all from a browser UI. Tear-down and snapshot management are equally first-class.

Prior to this, the user ran similar automation against Hyper-V from a Windows host. This is the Ubuntu/KVM equivalent, rebuilt as a web app rather than a standalone script.

**v1 scope:** Windows guests on KVM/QEMU on an Ubuntu host.
**Designed for future scope:** Any guest OS on KVM; remote management of Hyper-V VMs from a Linux host via WinRM.

## Naming and Branding

- **Hatchery** — the product/application name (the place where VMs are hatched)
- **Hatch** — the primary CLI verb and action language throughout the app (`hatch new`, `hatch destroy`, etc.)
- The egg/hatching metaphor is intentional and extends across all terminology (inspired by sci-fi/gaming dragon hatcheries and StarCraft Zerg hatcheries)

### Vocabulary

The terminology follows an avian/hatching metaphor. Branded terms are used where they add character or precision; standard terms are kept where the branded equivalent would add friction without benefit.

| Category | Standard Term | Hatchery Term | Meaning |
|---|---|---|---|
| Infrastructure | Host / Hypervisor | **Nest** | The physical or remote machine running Hatchery and managing VMs |
| Environment | Deployment group / Stack | **Clutch** | One or more related VMs defined together in a Clutch file |
| Source image | ISO / VHD / VHDX | **Egg** | A source image used to hatch a VM *(reserved — dormant, not currently used in UI or directory structure)* |
| All managed VMs | VM inventory | ~~Brood~~ *(retired)* | Dropped — use "VMs" or "Virtual Machines" in UI and code |
| Provision | Deploy / Provision | **Hatch** | Create and boot a VM |
| Provision + save | Deploy + export config | **Export and Hatch** | Save configuration as a Clutch file, then hatch |
| Save config only | Export / Blueprint | **Export Clutch** | Save configuration to a Clutch file without hatching |
| Destroy | Delete / Terminate | **Cull** | Destroy a VM and remove its allocated storage |
| Provisioned state | Ready / Healthy | **Fledged** | A VM that has completed provisioning and is ready to use |
| Snapshot | Snapshot / Save state | **Freeze** | Save a VM's disk and state at a point in time |
| Restore | Restore snapshot | **Thaw** | Restore a VM to a previously frozen state |
| Status check | Health check | **Chirp** | Lightweight ping to confirm a VM is responsive |
| Power on | Start | Start | — |
| Graceful shutdown | Shutdown | Stop | — |
| Forced shutdown | Force off | Force Stop | — |
| Suspend | Pause | Pause | — |
| Resume | Resume | Resume | — |

## Tech Stack

- **Backend**: Python + Flask
- **Frontend**: Vanilla HTML/CSS/JS (no framework) — served by Flask
- **Templating**: Jinja2 (for both UI templates and unattended install answer file generation)
- **VM control (KVM)**: `virt-install`, `virsh`, `qemu-img` via Python `subprocess`
- **VM control (Hyper-V, future)**: PowerShell cmdlets via WinRM from a remote Linux host
- **Post-install provisioning**: WinRM via `pywinrm` (Windows guests); SSH (Linux guests, future)
- **Dependencies**: `flask`, `pywinrm`, `pyyaml` (see `pyproject.toml`)

## Supported Guests (v1)

- Windows 10
- Windows 11 (requires UEFI + TPM 2.0 emulation via `swtpm`)
- Windows Server 2022
- Windows Server 2025 (requires UEFI + TPM 2.0 emulation via `swtpm`)

Each OS has its own answer file template under `templates/answerfiles/`.

## Architecture

```
Hatchery/
├── hatchery.py                   # Flask app, all API routes
├── lib/
│   ├── providers/
│   │   ├── base.py               # Abstract provider interface
│   │   ├── libvirt.py            # KVM/QEMU implementation (v1)
│   │   └── hyperv.py             # Hyper-V remote implementation (future)
│   ├── answerfile.py             # Unattended install file rendering (OS-aware)
│   └── provision.py              # Post-install provisioning (WinRM / SSH)
├── templates/
│   ├── ui/                       # HTML pages (Jinja2)
│   │   ├── index.html            # Dashboard: VM list + host stats
│   │   ├── create.html           # Hatch a new VM (the main form)
│   │   └── manage.html           # Per-VM controls: power, snapshots
│   └── answerfiles/              # Unattended install Jinja2 templates
│       ├── win10.xml.j2
│       ├── win11.xml.j2
│       ├── server2022.xml.j2
│       └── server2025.xml.j2
├── tests/                        # pytest test suite
├── static/
│   ├── style.css
│   └── app.js                    # Status polling, UI interactions
├── pyproject.toml
├── uv.lock
└── CLAUDE.md
```

## Provider Abstraction

All hypervisor operations go through a provider interface defined in `lib/providers/base.py`. Each provider implements:

- `list_vms()` — return all VMs known to the provider
- `create_vm(config)` — hatch a new VM
- `start_vm(name)` / `stop_vm(name)` / `force_stop_vm(name)`
- `destroy_vm(name)` — full teardown including disk removal
- `create_snapshot(name, label)` — freeze a VM state
- `list_snapshots(name)` — list frozen states
- `revert_snapshot(name, label)` — thaw to a saved state
- `delete_snapshot(name, label)` — delete a frozen state
- `get_status(name)` — running / shut off / paused / etc.

The libvirt provider calls `virt-install` / `virsh` via subprocess. The future Hyper-V provider will invoke PowerShell cmdlets over WinRM from the Linux host running Hatchery — keeping the user on their Linux machine without needing to switch to the Windows host for VM management.

## Answer File Generation (OS-Aware)

Answer file generation is OS-aware — not all guests require one:

| Guest type | Mechanism |
|---|---|
| Windows (KVM) | `Autounattend.xml` rendered from Jinja2 template, written to floppy image |
| Linux (KVM, future) | cloud-init seed ISO or preseed/kickstart depending on distro |
| Windows (Hyper-V, future) | `Autounattend.xml` transferred to Hyper-V host via WinRM |
| Linux (Hyper-V, future) | cloud-init config transferred via WinRM |

`answerfile.py` handles all of this — callers request an answer file by OS type; the module selects the appropriate strategy.

## Post-Install Provisioning

Provisioning is connection-type-aware:

| Guest type | Protocol | Notes |
|---|---|---|
| Windows | WinRM (`pywinrm`) | Enabled through the answer file on first boot |
| Linux (future) | SSH | Standard key-based auth |

After Windows first boot, `provision.py` connects over WinRM and installs:
- Chocolatey
- VS Code + Remote Development extension pack
- Python
- Go
- PowerShell (latest)
- OpenSSH server

## Key Features (v1 Scope)

### VM Creation Form (`/create`)
Inputs:
- VM name
- OS type (Win10 / Win11 / Server 2022 / Server 2025) — drives answer file template and UEFI/TPM requirements
- ISO path
- VirtIO driver ISO path (optional)
- vCPU count
- RAM (GB)
- Disk size (GB)
- Admin username + password (injected into answer file)

### Driver Support
- **VirtIO** (preferred): higher performance, requires VirtIO driver ISO at install time
- **Standard (IDE/e1000)**: zero extra setup, good fallback

### UEFI / TPM
- Win10 / Server 2022: BIOS boot works; UEFI optional
- Win11 / Server 2025: UEFI required + TPM 2.0 emulation via `swtpm`

### VM Lifecycle (`/manage/<vm-name>`)
- Start / Stop / Force Stop
- Cull — full teardown, removes disk
- Freeze — save VM state at a point in time
- Thaw — restore to a previously frozen state
- List and delete frozen states
- Chirp — lightweight status check

### Dashboard (`/`)
- Two-panel layout: Nest selector (left) and VM list (right)
- Lists all VMs with state (running / shut off / paused) and fledged status
- Host resource consumption (CPU, memory, storage)
- Quick-action buttons per VM
- JS polls `/api/status` every 5s for live updates

## VM Creation Routes

There are two routes to hatching a VM. Both share the same underlying schema — the ad-hoc route builds a Clutch entry interactively; the templated route reads one from a file.

### Ad-hoc

The user fills out the creation form in the UI. Three actions are available:

| Action | Behaviour |
|---|---|
| **Hatch** | Create the VM immediately — no file persistence |
| **Export and Hatch** | Save the configuration as a Clutch file, then hatch |
| **Export Clutch** | Save the configuration to a Clutch file without hatching |

Export actions support both creating a new Clutch file and appending a VM definition to an existing one, enabling incremental construction of multi-VM environments.

### Templated

The user selects an existing Clutch file from the UI. Hatchery reads the file and hatches all defined VMs in dependency order. No manual input required beyond selecting the file.

## Clutch Files

A Clutch file is a YAML file defining one or more related VMs to be hatched together. It is the portable, reusable unit of environment configuration in Hatchery.

A single-VM Clutch is valid. A multi-VM Clutch defines an environment — for example, an Active Directory test lab with a domain controller and a client.

**Multi-VM ordering:** Each VM entry may declare a `depends_on` list referencing other VMs in the same Clutch. VMs with no dependencies are hatched in parallel; dependent VMs wait until their prerequisites are fledged. This allows parallel provisioning where safe and sequential provisioning where required.

Clutch files are stored in the user data directory and managed through the Clutches pane in the UI.

## Data Directory

All user-generated and user-supplied assets live outside the Hatchery application source directory. This keeps the source directory portable and supports clean upgrades and reinstalls without touching user data.

**Default root:** `~/.local/share/hatchery/` (XDG-compliant; configurable via Settings)

```
~/.local/share/hatchery/
├── clutches/               # Clutch definition files (.yaml)
├── media/                  # Source images — ISOs, VHDs, VHDX, QCOW2
└── automation/
    ├── os_config/          # OS deployment config — Autounattend.xml, cloud-init, preseed
    └── scripts/            # Post-boot scripts — .ps1 (Windows), .sh (Linux)
```

Frozen VM states (snapshots) are managed by libvirt/virsh and remain in the hypervisor's storage — they are not duplicated in the data directory.

The data directory root is exposed as a setting so power users can point it at a NAS, shared storage, or any preferred location.

## UI Navigation

Five top-level navigation panes:

| Pane | Purpose |
|---|---|
| **Dashboard** | VM list and host resource consumption, scoped to the selected Nest |
| **Nests** | View and manage Nest host endpoints (local and future remote) |
| **Clutches** | View and manage Clutch files — create, edit, import, delete |
| **Automation** | View and manage automation files — OS answer files, post-first-boot scripts |
| **Settings** | Application configuration — data directory path, Nest connection settings |

## Design Principles

- Minimalist UI — functional over decorative
- No JS framework — vanilla HTML/CSS/JS only
- Automation-first — zero manual steps after clicking "Hatch"
- Provider-agnostic core — hypervisor differences are isolated in `lib/providers/`
- OS-aware, not OS-assuming — answer files and provisioning adapt to the guest type
- Errors surface in the UI, not just server logs
- **1:1:1 naming** — a concept has one name used identically in the UI, documentation, and codebase; if it is called "Clutch" in the UI it is `clutch` in the code and "Clutch" in the docs
- **Shallow data directory** — target ≤3 levels deep; prefer wider structure over deep nesting; directory names align with vocabulary

## Host Requirements

The Ubuntu host needs:

```bash
sudo apt install qemu-kvm libvirt-daemon-system virt-manager virtinst \
    swtpm swtpm-tools mtools python3 python3-gi
```

Install Python dependencies with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Running Hatchery

```bash
uv run gunicorn hatchery:app --bind 127.0.0.1:5000 --workers 1
# Opens at http://localhost:5000
```

---

## Project Conventions

### `.hatchery/` Directory

All project meta-content lives in `.hatchery/`: branding assets, documentation, audit artifacts, and UI mockups. Nothing in `.hatchery/` is required to run the application — it exists for project management, documentation, and contributor tooling. Build and deploy steps should exclude this directory entirely.

This convention is used across projects for consistency.

### Devcontainers

Devcontainers are intentionally not included. Hatchery requires direct access to the host's libvirt daemon and KVM stack (`virsh`, `virt-install`, `qemu-img`). A container cannot reach these host-level services without privileged container configuration that adds significant complexity with no practical benefit. Contributors run Hatchery directly on their Ubuntu host. See `CONTRIBUTING.md` for setup instructions.

### Git Workflow

All work must follow this flow without exception:

1. **Issue first** — every change must have a GitHub issue. If one does not exist, create it before starting.
2. **Branch per issue** — all commits go to a branch named for the issue. Never commit directly to `main`.
3. **PR to close** — open a pull request to merge the branch into `main`. Claude opens the PR; the human reviews and merges it. CI passing is a necessary condition, not a sufficient one — it cannot catch behavioral regressions in untested paths, UI changes, documentation accuracy, or architectural decisions.
4. **Cleanup** — after the PR merges, switch to `main`, pull, and delete the local branch:
   ```bash
   git checkout main && git pull && git branch -d <branch-name>
   ```

Before committing, always pause and ask: "Anything to add before I commit?" Wait for a response before proceeding to commit, push, and PR.

### Branches

Branch names use the commit type as a prefix, followed by the issue number and a short description:

```
feat/11-vm-snapshot-list
fix/10-virsh-timeout
chore/24-ruff-config
docs/26-getting-started-virtio
```

### Commits

Use conventional commit format with a short present-tense description and the issue number:

```
feat: add snapshot list to manage page (#11)
fix: resolve virsh timeout on slow hosts (#10)
docs: update getting-started with VirtIO setup (#26)
chore: pin ruff version in pyproject.toml (#24)
refactor: extract answer file strategy to separate classes (#18)
sec: restrict WinRM credential storage to session scope (#31)
breaking: rename /api/vms to /api/brood (#7)
```

| Prefix | When |
|---|---|
| `feat:` | New feature or user-facing change |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `chore:` | Maintenance, tooling, non-functional |
| `refactor:` | Code restructure with no behavior change |
| `sec:` | Security fix or audit finding |
| `breaking:` | Backwards-incompatible change |

### Issues and Labels

Every issue must have exactly one label matching its commit type prefix:

| Label | Commit prefix | When |
|---|---|---|
| `feat` | `feat:` | New feature or user-facing enhancement |
| `fix` | `fix:` | Bug fix |
| `chore` | `chore:` | Maintenance, tooling, non-functional |
| `refactor` | `refactor:` | Code restructure, no behavior change |
| `docs` | `docs:` | Documentation only |
| `sec` | `sec:` | Security audit, vulnerability fix |
| `breaking` | `breaking:` | Backwards-incompatible change |

Additional triage labels (`wontfix`, `question`, `help wanted`, `good first issue`, `dependencies`) may be applied alongside the type label when relevant.

### Pull Requests

- One concern per PR
- Tests required for new features and bug fixes — a PR that adds or modifies functionality without tests will not be merged
- All CI checks (lint, test) must pass before merge — CI is a necessary condition, not a sufficient one
- If behavior changed, update the relevant `.hatchery/docs/`, `README.md`, or `CONTRIBUTING.md` before opening the PR
- PR description explains the *why*, not just the *what*

### Working with Claude

- Do not commit unless explicitly asked — and before committing, pause and ask "Anything to add before I commit?" Wait for a response before proceeding to commit, push, and PR
- Do not push unless explicitly asked
- Do not create, close, or comment on issues/PRs without being asked
- When implementing a feature, check the existing provider interface before adding new methods
- Prefer editing existing files over creating new ones
- Do not add abstraction layers beyond what the current task requires

### Python Style

- Formatter and linter: `ruff`
- Line length: 100
- Run checks: `uv run ruff check . && uv run ruff format --check .`
- Auto-fix: `uv run ruff check --fix . && uv run ruff format .`

### Testing

Tests are written alongside implementation — never as a follow-up. A PR that adds or modifies a function without an accompanying test will not be merged.

Before every push and every PR, all checks must pass locally:

1. **Lint** — zero violations:
   ```bash
   uv run ruff check . && uv run ruff format --check .
   ```
2. **Tests** — all passing, ≥60% line coverage:
   ```bash
   uv run pytest
   ```
3. **Docs** — if behavior changed, update `.hatchery/docs/`, `README.md`, or `CONTRIBUTING.md`

Nothing reaches the repo that isn't clean, tested, and documented.

---

## Future Scope

### Multiple Nests

v1 manages a single local Nest (the host running Hatchery). Future versions will support registering multiple Nests — local or remote — and managing their VMs from a single Hatchery instance. The Nests pane in the UI is designed for this from the start.

### Any Guest OS on KVM

The provider abstraction and OS-aware answer file/provisioning system are already designed to support Linux guests on KVM. Adding a new guest type means:
1. Adding an answer file template (or cloud-init config) under `templates/answerfiles/`
2. Adding provisioning logic to `provision.py` (SSH-based for Linux)
3. Registering the OS type in the creation form

### Remote Hyper-V Management

The Hyper-V provider (`lib/providers/hyperv.py`) will manage VMs on a remote Windows host via WinRM. The user runs Hatchery on their Linux machine; Hatchery connects to the Windows host, invokes PowerShell Hyper-V cmdlets over WinRM, and presents the same UI/API as the KVM provider. This allows a Linux developer to manage their Hyper-V VMs without switching OS context or maintaining a separate tooling environment on Windows.

Key differences from the libvirt provider:
- All VM operations invoke PowerShell Hyper-V cmdlets via `pywinrm`
- Answer files are transferred to the Hyper-V host over WinRM
- Configuration requires a Hyper-V host address + WinRM credentials

---

## Related Notes

`Dev_SetupEnvironments` repo (`~/workspaces/Dev_SetupEnvironments/Computers/temp_virtualmachinemanager.md`) contains earlier notes on importing VHD/VHDX files into Virt-Manager — useful reference for the `qemu-img convert` approach if users want to import existing eval disk images rather than installing from ISO.
