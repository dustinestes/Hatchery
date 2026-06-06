<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Customization</h1>
<br clear="both">

How to customize Hatchery — provisioning scripts, VM configuration profiles, and answer file templates.

<br>

## Contents

- [Contents](#contents)
- [Provisioning Scripts](#provisioning-scripts)
- [Answer File Templates](#answer-file-templates)
- [Adding a New Guest OS](#adding-a-new-guest-os)

---

<br>

## Provisioning Scripts

Post-install provisioning is defined in `lib/provision.py`. The default sequence installs Chocolatey, VS Code, Python, Go, PowerShell, and OpenSSH. To add, remove, or change what gets installed, edit the WinRM command list in `provision.py`.

---

<br>

## Answer File Templates

Answer file templates live in `templates/answerfiles/`. Each file is a Jinja2 template rendered with the values from the VM creation form. To adjust locale, keyboard layout, timezone, or first-boot scripts, edit the relevant `*.xml.j2` file.

Variables available in all Windows answer file templates:

| Variable | Source |
|---|---|
| `vm_name` | VM name from the creation form |
| `admin_username` | Admin username from the form |
| `admin_password` | Admin password from the form |

---

<br>

## Adding a New Guest OS

To add support for a new guest OS:

1. Create an answer file template in `templates/answerfiles/` (or a cloud-init config for Linux)
2. Add an entry to `answerfile.py` mapping the OS type to the template and generation strategy
3. Add the OS type to the creation form options in `templates/ui/create.html`
4. Register any UEFI/TPM requirements in the provider's `create_vm` method

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Where environments hatch</div>
<br clear="both">
