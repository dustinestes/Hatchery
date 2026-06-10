<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Project Structure</h1>
<br clear="both">

Root directory layout and purpose of every file and folder in Hatchery.

<br>

## Contents

- [Contents](#contents)
- [Directory Tree](#directory-tree)
- [Files and Folders](#files-and-folders)

---

<br>

## Directory Tree

```
Hatchery/
├── .hatchery/                    # Project meta — not required to run the application
│   ├── audits/                   # Security and quality audit artifacts
│   ├── branding/                 # SVG logos, icons, banners, and brand guidelines
│   ├── docs/                     # Reference documentation (this directory)
│   └── ui/                       # Interface mockups and interactive examples
├── .github/
│   ├── workflows/
│   │   ├── lint.yml              # Ruff lint + format check
│   │   └── test.yml              # pytest with coverage
│   └── dependabot.yml
├── .vscode/
│   ├── launch.json               # Flask debug configuration
│   └── settings.json             # Python + ruff settings
├── hatchery.py                   # Flask app entry point, all API routes
├── scripts/
│   ├── hatchery.service          # systemd user unit template
│   ├── install-service.sh        # installs the systemd service and optional hostname
│   └── uninstall-service.sh      # removes the service and hostname entry
├── lib/
│   ├── providers/
│   │   ├── base.py               # Abstract provider interface
│   │   ├── libvirt.py            # KVM/QEMU implementation (v1)
│   │   └── hyperv.py             # Hyper-V remote implementation (future)
│   ├── answerfile.py             # Unattended install file rendering (OS-aware)
│   └── provision.py              # Post-install provisioning (WinRM / SSH)
├── templates/
│   ├── ui/                       # HTML pages rendered by Flask/Jinja2
│   │   ├── index.html            # Dashboard — brood list and status
│   │   ├── create.html           # Hatch a new VM
│   │   └── manage.html           # Per-VM controls — power, snapshots
│   └── answerfiles/              # Unattended install Jinja2 templates
│       ├── win10.xml.j2
│       ├── win11.xml.j2
│       ├── server2022.xml.j2
│       └── server2025.xml.j2
├── tests/                        # pytest test suite
├── static/
│   ├── style.css
│   └── app.js                    # Status polling, UI interactions
├── pyproject.toml                # Project metadata, dependencies, tool config
├── uv.lock                       # Locked dependency versions
├── CLAUDE.md                     # Project context and conventions for Claude
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

---

<br>

## Files and Folders

### `hatchery.py`

Flask entry point. Defines all routes: the dashboard (`/`), single-VM hatch form (`/hatch`), clutch build form (`/build`), and all API endpoints. Instantiates the active provider and passes it to route handlers.

### `scripts/`

Service installation helpers. Run `bash scripts/install-service.sh` to install Hatchery as a systemd user service — the script detects the install directory and `uv` path automatically. Run `bash scripts/uninstall-service.sh` to remove the service and any `/etc/hosts` entry. See [Getting Started — Running as a Service](getting-started.md#running-as-a-service).

### `lib/providers/`

Hypervisor abstraction layer. All VM operations go through the interface defined in `base.py`. Add a new hypervisor by implementing that interface — nothing else changes.

| File | Purpose |
|---|---|
| `base.py` | Abstract base class — all providers must implement this interface |
| `libvirt.py` | KVM/QEMU via `virt-install` and `virsh` subprocess calls |
| `hyperv.py` | Hyper-V via WinRM + PowerShell cmdlets (future) |

### `lib/answerfile.py`

OS-aware unattended install file generation. Selects the appropriate strategy (Autounattend.xml for Windows, cloud-init for Linux) based on the guest OS type and renders the Jinja2 template with the provided configuration.

### `lib/provision.py`

Post-install provisioning. Connects to the guest over WinRM (Windows) or SSH (Linux, future) and runs the provisioning sequence.

### `templates/ui/`

Jinja2 HTML templates served by Flask. No frontend framework — vanilla HTML, CSS, and JS only.

### `templates/answerfiles/`

Jinja2 templates for unattended install answer files. One template per supported guest OS.

### `tests/`

pytest test suite. Mirrors the structure of `lib/`. Run with `uv run pytest`.

### `.hatchery/`

Project meta-content. Not required to run the application. Excluded from deployments. See [.hatchery/docs/README.md](README.md) for the documentation index.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Where environments hatch</div>
<br clear="both">
