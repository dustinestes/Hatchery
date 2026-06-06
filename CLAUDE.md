# Hatchery

A local web application for creating, provisioning, and managing Windows guest VMs on an Ubuntu host using QEMU/KVM (libvirt / Virtual Machine Manager).

## Origin and Context

Designed for a developer who works on an Ubuntu host and needs Windows guest VMs (Win10, Win11, Server 2022, Server 2025) for development targeting Windows environments. The goal is full automation: create a VM, run an unattended Windows install, provision dev tools, and have a ready environment — all from a browser UI. Tear-down and snapshot management are equally first-class.

Prior to this, the user ran similar automation against Hyper-V from a Windows host. This is the Ubuntu/KVM equivalent, rebuilt as a web app rather than a standalone script.

## Naming and Branding

- **Hatchery** — the product/application name (the place where VMs are hatched)
- **Hatch** — the primary CLI verb and action language throughout the app (`hatch new`, `hatch destroy`, etc.)
- The egg/hatching metaphor is intentional and extends across all terminology (inspired by sci-fi/gaming dragon hatcheries and StarCraft Zerg hatcheries)

### Vocabulary

| Term | Meaning |
|---|---|
| Egg | A Windows ISO image (the source material) |
| Hatch / Hatching | Creating and booting a new VM |
| Fledged | A VM that has completed provisioning and is ready to use |
| Clutch | A named configuration/profile for a VM type |
| Nest | A snapshot (a saved state to return to) |
| Roost | The snapshot restore operation |
| Brood | The full list of VMs managed by Hatchery |

## Tech Stack

- **Backend**: Python + Flask
- **Frontend**: Vanilla HTML/CSS/JS (no framework) — served by Flask
- **Templating**: Jinja2 (for both UI templates and Autounattend.xml answer file generation)
- **VM control**: `virt-install`, `virsh`, `qemu-img` via Python `subprocess`
- **Post-install provisioning**: WinRM via `pywinrm` (WinRM enabled through the answer file on first boot)
- **Dependencies**: `flask`, `pywinrm`, `jinja2` (see `requirements.txt`)

## Supported Guest OS

- Windows 10
- Windows 11 (requires UEFI + TPM 2.0 emulation via `swtpm`)
- Windows Server 2022
- Windows Server 2025 (requires UEFI + TPM 2.0 emulation via `swtpm`)

Each OS has its own `Autounattend.xml` Jinja2 template under `templates/answerfiles/`.

## Architecture

```
Hatchery/
├── app.py                        # Flask app, all API routes
├── lib/
│   ├── vm.py                     # virt-install / virsh wrappers
│   ├── answerfile.py             # Autounattend.xml rendering
│   └── provision.py              # WinRM post-install provisioning
├── templates/
│   ├── ui/                       # HTML pages (Jinja2)
│   │   ├── index.html            # Dashboard: brood list + status
│   │   ├── create.html           # Hatch a new VM (the main form)
│   │   └── manage.html           # Per-VM controls: power, snapshots
│   └── answerfiles/              # Autounattend.xml Jinja2 templates
│       ├── win10.xml.j2
│       ├── win11.xml.j2
│       ├── server2022.xml.j2
│       └── server2025.xml.j2
├── static/
│   ├── style.css
│   └── app.js                    # Status polling, UI interactions
├── requirements.txt
└── CLAUDE.md
```

## Key Features (v1 Scope)

### VM Creation Form (`/create`)
Inputs:
- VM name
- OS type (Win10 / Win11 / Server 2022 / Server 2025) — drives answer file template selection and UEFI/TPM requirements
- ISO path (user's own eval/licensed ISOs)
- VirtIO driver ISO path (optional — enables VirtIO disk+network for better performance; falls back to IDE/e1000 if omitted)
- vCPU count
- RAM (GB)
- Disk size (GB)
- Admin username + password (injected into answer file)

### Driver Support
- **VirtIO** (preferred): higher performance, requires VirtIO driver ISO injected alongside Windows ISO at install time
- **Standard (IDE/e1000)**: lower performance, zero extra setup, good fallback

### UEFI / TPM
- Win10 / Server 2022: BIOS boot works; UEFI optional
- Win11 / Server 2025: UEFI required + TPM 2.0 emulation via `swtpm`
- The OS type selection in the form automatically configures `virt-install` flags accordingly

### Answer File Generation
- Form inputs are rendered into the appropriate `*.xml.j2` template
- Answer file is written to a temp floppy image (`.img`) mounted as a virtual floppy drive so Windows Setup finds it automatically
- Handles: locale, keyboard, timezone, auto-login, WinRM enable, first-boot PowerShell provisioning trigger

### Post-Install Provisioning (via WinRM)
After Windows first boot, `provision.py` connects over WinRM and installs:
- Chocolatey (package manager)
- VS Code + Remote Development extension pack
- Python
- Go
- PowerShell (latest)
- OpenSSH server (enables VS Code Remote SSH from Ubuntu host)

### VM Lifecycle (`/manage/<vm-name>`)
- Start / Shutdown / Force off
- Destroy + undefine (full teardown, removes disk)
- Snapshot: create named nest
- Snapshot: list all nests
- Snapshot: revert to nest (roost)
- Snapshot: delete nest

### Dashboard (`/`)
- Lists all VMs (`virsh list --all`)
- Shows state (running / shut off / paused)
- Quick-action buttons per VM
- JS polls `/api/status` every 5s for live updates

## Design Principles

- Minimalist UI — functional over decorative
- No JS framework — vanilla HTML/CSS/JS only
- Automation-first — the goal is zero manual steps after clicking "Hatch"
- All VM operations are idempotent where possible
- Errors surface in the UI, not just server logs

## Host Requirements

The Ubuntu host needs these packages before running Hatchery:

```bash
sudo apt install qemu-kvm libvirt-daemon-system virt-manager virtinst \
    libguestfs-tools swtpm swtpm-tools python3 python3-pip
pip install flask pywinrm
```

## Running Hatchery

```bash
python app.py
# Opens at http://localhost:5000
```

## Related Notes

The `Dev_SetupEnvironments` repo (`~/workspaces/Dev_SetupEnvironments/Computers/temp_virtualmachinemanager.md`) contains earlier notes on manually importing VHD/VHDX files into Virt-Manager — useful reference for the `qemu-img convert` approach if users want to import existing eval disk images rather than installing from ISO.
