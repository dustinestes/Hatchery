<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
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
├── docs/                         # First-class reference documentation (this directory)
│   ├── adr/                      # Architecture Decision Records
│   ├── schema/                   # Clutch YAML + database schema references
│   └── assets/                   # Screenshots and doc images
├── .hatchery/                    # Project meta — not required to run the application
│   ├── audits/                   # Security and quality audit artifacts
│   ├── branding/                 # Brand assets — dragon scale mark (icons/logos/banners); dragon_egg.svg kept for history
│   ├── examples/                 # Sample scripts and fixtures
│   ├── tooling/                  # Contributor harnesses (e.g. Artifactory OSS)
│   └── ui/                       # Interface mockups and interactive examples
├── .github/
│   ├── workflows/
│   │   ├── lint.yml              # Ruff lint + format check
│   │   └── test.yml              # pytest matrix (Linux / macOS / Windows)
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
│   ├── nest_transport.py         # Nest control plane (SSH default; key reference)
│   ├── import_files.py           # UI Import — create-only copy into data dir
│   └── provision.py              # Post-install guest provisioning (WinRM / SSH)
├── templates/
│   ├── ui/                       # HTML pages rendered by Flask/Jinja2
│   │   ├── index.html            # Dashboard - at-a-glance tile shell (#328)
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
| `hyperv.py` | Hyper-V via Nest transport + PowerShell (SSH default #218; WinRM Nest #220) |

Feature support vs Nest type (local/remote): [Provider and feature support matrix](providers.md).

### `lib/nest_transport.py`

Nest **control plane** — Hatchery → Nest host. Default remote transport is SSH with a referenced OpenSSH identity (no private-key storage). WinRM is an explicit Nest fallback for Windows hosts. See [Nest transport](nest-transport.md). Nest SSH identity expiry alerts: [Nest SSH identity expiry](nest-key-expiry.md). Guest WinRM stays in `provision.py`.

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

### `docs/`

First-class product and contributor documentation (operators + architecture). See [Documentation index](README.md).

### `.hatchery/`

Project meta-content (branding, examples, tooling, audits, UI mocks). Not required to run the application. Excluded from deployments.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
