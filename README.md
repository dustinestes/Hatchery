<br/><br/>

<div align="center">

<br/>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset=".hatchery/branding/logos/hatchery-logo-dark.svg">
  <img alt="Hatchery" src=".hatchery/branding/logos/hatchery-logo-light.svg" height="60">
</picture>

<br/><br/>

![License](https://img.shields.io/badge/license-MIT-111111?style=flat-square&labelColor=555555)
![Version](https://img.shields.io/badge/version-v0.1.0-111111?style=flat-square&labelColor=555555)
![Platform](https://img.shields.io/badge/platform-Ubuntu%20%7C%20KVM-111111?style=flat-square&labelColor=555555)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/dustin-estes/hatchery/lint.yml?style=flat-square&label=Lint&labelColor=555555)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/dustin-estes/hatchery/test.yml?style=flat-square&label=Tests&labelColor=555555)

<br/>

</div>

<br/><br/>

---

Hatchery is a local web application for creating, provisioning, and managing VMs — Windows-first on KVM/QEMU, built to grow toward any guest OS and remote Hyper-V management. Point it at an ISO, fill in a form, and get a fully provisioned VM without touching a terminal.

---

<br/>

## What It Does

- **Hatch VMs** — create Windows VMs from ISO with fully unattended installs via `Autounattend.xml`
- **Provision automatically** — installs Chocolatey, VS Code, Python, Go, PowerShell, and OpenSSH over WinRM after first boot
- **Manage the full lifecycle** — start, stop, destroy, snapshot, and restore from a browser UI
- **Stay out of the way** — zero manual steps from "Hatch" to a ready development environment

---

<br/>

## What It's Made Of

### Project Structure

```
Hatchery/
├── app.py                        # Flask app, all API routes
├── lib/
│   ├── providers/
│   │   ├── base.py               # Abstract provider interface
│   │   ├── libvirt.py            # KVM/QEMU implementation (v1)
│   │   └── hyperv.py             # Hyper-V remote implementation (future)
│   ├── answerfile.py             # Unattended install file rendering (OS-aware)
│   └── provision.py              # Post-install provisioning (WinRM / SSH)
├── templates/
│   ├── ui/                       # HTML pages (Jinja2)
│   └── answerfiles/              # Autounattend.xml Jinja2 templates
├── tests/                        # pytest test suite
├── static/
│   ├── style.css
│   └── app.js
├── requirements.txt
└── requirements-dev.txt
```

> Full structure guide → [Project Structure](.hatchery/docs/project-structure.md)

---

<br/>

## What It Supports

| Guest OS | Provider | Status |
|---|---|---|
| Windows 10 | KVM/QEMU | v1 |
| Windows 11 | KVM/QEMU | v1 — requires UEFI + TPM |
| Windows Server 2022 | KVM/QEMU | v1 |
| Windows Server 2025 | KVM/QEMU | v1 — requires UEFI + TPM |
| Linux guests | KVM/QEMU | Planned |
| Windows (Hyper-V) | Remote via WinRM | Planned |

---

<br/>

## What It Requires

| Requirement | Notes |
|---|---|
| Ubuntu host | KVM-capable hardware |
| `qemu-kvm`, `libvirt`, `virtinst` | VM control stack |
| `swtpm`, `swtpm-tools` | TPM emulation (Win11 / Server 2025) |
| Python 3.x | Runtime |
| Windows ISO(s) | Your own eval or licensed copies |
| VirtIO driver ISO | Optional — higher performance disk/network |

```bash
sudo apt install qemu-kvm libvirt-daemon-system virt-manager virtinst \
    libguestfs-tools swtpm swtpm-tools python3 python3-pip
```

---

<br/>

## Where To Start

1. **Install host dependencies** — see requirements above
2. **Clone and install Python deps** — `pip install -r requirements.txt`
3. **Run Hatchery** — `python app.py`
4. **Open the dashboard** — `http://localhost:5000`
5. **Hatch a VM** — go to `/create`, fill in the form, click Hatch

> Getting Started → [Getting Started Guide](.hatchery/docs/getting-started.md)

---

<br/>

## What's Planned Next

- **Planned and in-progress** → [GitHub Issues](https://github.com/dustin-estes/hatchery/issues)
- **Shipped by version** → [GitHub Releases](https://github.com/dustin-estes/hatchery/releases)

---

<br/>

## How to Contribute

Contributions, ideas, and feedback are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

<br/>

## How It's Licensed

MIT License. See [LICENSE](LICENSE) for full terms.

---

<br/>

## With Thanks To

- **Dustin Estes** — creator, product design, and development
- **[Claude](https://claude.ai) (Anthropic)** — AI development assistant

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset=".hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src=".hatchery/branding/logos/hatchery-logo-light.svg" height="32" alt="Hatchery">
</picture>
<div align="right">hatch, provision, and manage VMs</div>
<br clear="both">
