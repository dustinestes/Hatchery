<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Getting Started</h1>
<br clear="both">

How to set up your Ubuntu host and hatch your first VM.

<br>

## Contents

- [Contents](#contents)
- [Host Requirements](#host-requirements)
- [Installation](#installation)
- [Running Hatchery](#running-hatchery)
- [Hatching Your First VM](#hatching-your-first-vm)
- [VirtIO Drivers](#virtio-drivers)
- [Windows 11 and Server 2025](#windows-11-and-server-2025)

---

<br>

## Host Requirements

Hatchery runs on an Ubuntu host with KVM/QEMU available. You'll need:

- KVM-capable hardware (Intel VT-x or AMD-V, enabled in BIOS)
- Ubuntu 22.04 or later
- Your own Windows ISO files (evaluation ISOs from Microsoft work fine)

Install the required system packages:

```bash
sudo apt install qemu-kvm libvirt-daemon-system virt-manager virtinst \
    libguestfs-tools swtpm swtpm-tools python3
```

Add your user to the `libvirt` and `kvm` groups so you can manage VMs without `sudo`:

```bash
sudo usermod -aG libvirt,kvm $USER
# Log out and back in for the group change to take effect
```

---

<br>

## Installation

Install [uv](https://docs.astral.sh/uv/) if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Clone and install:

```bash
git clone https://github.com/dustin-estes/hatchery.git
cd hatchery
uv sync
```

`uv sync` creates a virtual environment at `.venv` and installs all dependencies from `uv.lock`.

---

<br>

## Running Hatchery

```bash
uv run python app.py
```

Open `http://localhost:5000` in your browser. The dashboard shows your current brood (all VMs known to libvirt).

---

<br>

## Hatching Your First VM

1. Go to `http://localhost:5000/create`
2. Fill in the form:
   - **VM name** — a short identifier, e.g. `win10-dev`
   - **OS type** — selects the answer file template and configures UEFI/TPM automatically
   - **ISO path** — absolute path to your Windows ISO on the host
   - **vCPUs, RAM, Disk** — size to taste; 4 vCPUs / 8 GB RAM / 80 GB disk is a reasonable default
   - **Admin username + password** — injected into the answer file; used for the local administrator account
3. Click **Hatch**
4. Hatchery creates the VM, generates the `Autounattend.xml` answer file, and boots the installer
5. Windows installs unattended — no interaction needed
6. After first boot, Hatchery connects over WinRM and runs the provisioning sequence

The VM appears on the dashboard while hatching. Provisioning completes in the background; the VM status updates to **fledged** when ready.

---

<br>

## VirtIO Drivers

For better disk and network performance, pass a VirtIO driver ISO alongside the Windows ISO. Download the latest stable ISO from the [Fedora VirtIO project](https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/).

In the creation form, fill in the **VirtIO driver ISO path** field with the absolute path to the driver ISO. Hatchery will configure the VM to use VirtIO disk and network adapters and make the driver ISO available during install.

Leave this field empty to use standard IDE/e1000 adapters — slower, but zero extra setup.

---

<br>

## Windows 11 and Server 2025

These OS versions require UEFI firmware and TPM 2.0 emulation. Hatchery configures both automatically when you select Win11 or Server 2025 as the OS type — `swtpm` handles the TPM emulation. No manual steps required beyond having `swtpm` and `swtpm-tools` installed on the host.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Where environments hatch</div>
<br clear="both">
