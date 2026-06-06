<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="40" alt="Hatchery">
</picture>
<h1>Examples</h1>
<br clear="both">

Real-world scenarios for hatching, managing, and tearing down VMs with Hatchery.

<br>

## Contents

- [Contents](#contents)
- [Hatch a Windows 10 Dev VM](#hatch-a-windows-10-dev-vm)
- [Snapshot Before a Risky Change](#snapshot-before-a-risky-change)
- [Revert to a Clean Snapshot](#revert-to-a-clean-snapshot)
- [Tear Down a VM](#tear-down-a-vm)
- [Hatch a Windows 11 VM](#hatch-a-windows-11-vm)

---

<br>

## Hatch a Windows 10 Dev VM

1. Place your `Win10.iso` and `virtio-win.iso` somewhere accessible on the host
2. Go to `/create`
3. Fill in:
   - Name: `win10-dev`
   - OS: Windows 10
   - ISO: `/path/to/Win10.iso`
   - VirtIO ISO: `/path/to/virtio-win.iso`
   - vCPUs: 4, RAM: 8, Disk: 80
   - Admin credentials: your choice
4. Click Hatch — Windows installs unattended, provisioning runs automatically

---

<br>

## Snapshot Before a Risky Change

From the manage page (`/manage/win10-dev`):
1. Under **Nests**, enter a label: `before-sql-install`
2. Click **Create Nest**
3. Proceed with your change — if it breaks, revert with one click

---

<br>

## Revert to a Clean Snapshot

From the manage page:
1. Under **Nests**, find `before-sql-install`
2. Click **Roost** — the VM state reverts instantly

---

<br>

## Tear Down a VM

From the manage page:
1. Click **Destroy**
2. Hatchery stops the VM, undefines it from libvirt, and removes the disk image

This is irreversible — make a nest first if you want a recovery point.

---

<br>

## Hatch a Windows 11 VM

Same as the Windows 10 flow, but:
- Select **Windows 11** as the OS type
- Hatchery automatically configures UEFI firmware and `swtpm` TPM 2.0 emulation — no manual steps

---

<br>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="32" alt="Hatchery">
</picture>
<div align="right">hatch, provision, and manage VMs</div>
<br clear="both">
