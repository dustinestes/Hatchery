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
  - [System Packages](#system-packages)
  - [Group Membership](#group-membership)
  - [Media Access](#media-access)
  - [If Requirements Are Missing](#if-requirements-are-missing)
- [Installation](#installation)
- [Running Hatchery](#running-hatchery)
- [Hatching Your First VM](#hatching-your-first-vm)
- [VirtIO Drivers](#virtio-drivers)
- [Windows 11 and Server 2025](#windows-11-and-server-2025)
- [Appendix: Alternative Media Access Configurations](#appendix-alternative-media-access-configurations)
  - [Open world-execute on the path chain](#open-world-execute-on-the-path-chain)
  - [Move the data directory outside `/home`](#move-the-data-directory-outside-home)

---

<br>

## Host Requirements

Hatchery runs on an Ubuntu host with KVM/QEMU available. You'll need:

- KVM-capable hardware (Intel VT-x or AMD-V, enabled in BIOS)
- Ubuntu 22.04 or later
- Your own Windows ISO files (evaluation ISOs from Microsoft work fine)

### System Packages

Install the required system packages:

```bash
sudo apt install qemu-system-x86 libvirt-daemon-system virt-manager virtinst \
    libguestfs-tools swtpm swtpm-tools python3 python3-gi
```

> **Note:** On older Ubuntu releases, `qemu-kvm` is a valid alias for `qemu-system-x86`. On 24.04 and later, `qemu-kvm` is a virtual package that may not resolve correctly — use `qemu-system-x86` directly.

### Group Membership

Add your user to the `libvirt` and `kvm` groups so you can manage VMs without `sudo`:

```bash
sudo usermod -aG libvirt,kvm $USER
# Log out and back in for the group change to take effect
```

### Media Access

Before Hatchery can create a VM, the QEMU process needs to be able to read the ISO file from the media directory. QEMU runs as the `libvirt-qemu` system user, not as your own account. How you satisfy this depends on where your media lives.

**Local storage** (default) — Your media directory is under your home directory (`~/.local/share/hatchery/media/`). Home directories are typically mode `750` — no world-execute bit — so `libvirt-qemu` cannot traverse into them. Configure QEMU to run as your user account instead:

```bash
sudo nano /etc/libvirt/qemu.conf
```

Find and set these two lines (uncomment them if they are commented out):

```
user = "your-username"
group = "your-username"
```

Then restart libvirtd to apply the change:

```bash
sudo systemctl restart libvirtd
```

QEMU will now run with your user's permissions and can access files anywhere your account can.

**Remote / NAS storage** — If your media directory is on a network mount or outside `/home` (e.g. `/mnt/nas/hatchery/media/`), paths outside `/home` are world-traversable by default and `libvirt-qemu` can access them without any configuration change. Point Hatchery's data directory at your mount via Settings.

If Hatchery detects a permission problem when you click Hatch, it will surface the exact `chmod` command needed and record a warning in the notification system. See the [Appendix](#appendix-alternative-media-access-configurations) for fallback options if you cannot configure QEMU to run as your user.

### If Requirements Are Missing

If any required tools are not installed when you start Hatchery, a warning is recorded in the notification system. The bell icon in the top navigation bar will show a badge; open it to see the exact `apt install` command needed to resolve each missing tool. The warning clears automatically the next time you start Hatchery after the packages are installed.

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

1. Copy your Windows ISO into the media directory:
   ```bash
   cp /path/to/Win11.iso ~/.local/share/hatchery/media/
   ```
2. Go to `http://localhost:5000/create`
3. Fill in the form:
   - **VM name** — a short identifier, e.g. `win11-dev`
   - **Guest OS** — selects the answer file template and configures UEFI/TPM automatically
   - **OS Media** — select your ISO from the dropdown (refresh the list if you just added it)
   - **vCPUs, RAM, Disk** — 4 vCPUs / 8 GB RAM / 80 GB disk is a reasonable default
4. Click **Hatch**
5. Hatchery creates the VM, generates the `Autounattend.xml` answer file, and boots the installer
6. Windows installs unattended — no interaction needed
7. After first boot, Hatchery connects over WinRM and runs the provisioning sequence

The VM appears on the dashboard while hatching. Provisioning completes in the background; the VM status updates to **fledged** when ready.

---

<br>

## VirtIO Drivers

For better disk and network performance, pass a VirtIO driver ISO alongside the Windows ISO. Download the latest stable ISO from the [Fedora VirtIO project](https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/) and copy it into your media directory.

In the creation form, select it from the **VirtIO Drivers** dropdown. Hatchery will configure the VM to use VirtIO disk and network adapters and make the driver ISO available during install.

Leave this field empty to use standard IDE/e1000 adapters — slower, but zero extra setup.

---

<br>

## Windows 11 and Server 2025

These OS versions require UEFI firmware and TPM 2.0 emulation. Hatchery configures both automatically when you select Win11 or Server 2025 as the OS type — `swtpm` handles the TPM emulation. No manual steps required beyond having `swtpm` and `swtpm-tools` installed on the host.

---

<br>

## Appendix: Alternative Media Access Configurations

The recommended setup configures QEMU to run as your user (described in [Media Access](#media-access) above). If that is not possible, two alternatives exist.

### Open world-execute on the path chain

Grant `libvirt-qemu` traversal rights on each directory between `/` and your media file without changing who QEMU runs as. For the default data directory location:

```bash
chmod o+x /home/your-username
chmod o+x /home/your-username/.local
chmod o+x /home/your-username/.local/share
chmod o+x /home/your-username/.local/share/hatchery
chmod o+x /home/your-username/.local/share/hatchery/media
```

Individual files also need world-read if they do not already have it:

```bash
chmod o+r /home/your-username/.local/share/hatchery/media/Win11.iso
```

This works but opens more of your home directory to system users than necessary. Remote data directory is preferable on shared or multi-user systems.

### Move the data directory outside `/home`

Store media on a path that is world-traversable by default — a network mount or a dedicated directory under `/srv` or `/var`:

```bash
sudo mkdir -p /srv/hatchery
sudo chown $USER:$USER /srv/hatchery
```

Point Hatchery's data directory at this path via **Settings**. Directories outside `/home` are typically mode `755`, so `libvirt-qemu` can access them without any permission changes. This is the natural fit for NAS or shared-storage setups.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Where environments hatch</div>
<br clear="both">
