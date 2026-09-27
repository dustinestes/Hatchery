<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Customization</h1>
<br clear="both">

How to customize Hatchery - provisioning scripts, VM configuration profiles, and Answer Files.

<br>

## Contents

- [Contents](#contents)
- [Provisioning Scripts](#provisioning-scripts)
- [Answer Files](#answer-files)
- [Adding a New Guest OS](#adding-a-new-guest-os)

---

<br>

## Provisioning Scripts

Post-install provisioning is defined in `lib/provision.py`. The default sequence installs Chocolatey, VS Code, Python, Go, PowerShell, and OpenSSH. To add, remove, or change what gets installed, edit the WinRM command list in `provision.py`.

For operator-authored post-boot scripts, see [Automation Scripts](automations.md).

---

<br>

## Answer Files

Install-time unattended templates (Autounattend and future Linux seeds) are **Answer Files**. Operator how-to, tokens, companions, and per-OS notes: [Answer Files](answer-files.md). Architecture: [ADR-0024](adr/0024-answer-files-product-model.md).

Windows hatch requires a selected Answer File under `automation/answerfiles/` (pull Library samples or author your own). Admin credentials inject reserved system tokens for hatch through fledged; they do not select a hidden Controller template. After fledged, rotate the hatch admin yourself if the guest outlives setup ([Answer Files - Hatch-scoped through fledged](answer-files.md#hatch-scoped-through-fledged)).

---

<br>

## Adding a New Guest OS

To add support for a new guest OS:

1. Add an Answer File sample/strategy for that OS (see [Answer Files](answer-files.md)) and Nest attach capability
2. Extend hatch render / validation in `lib/answerfile.py` and the Guest OS enum as needed
3. Add the OS type to the Clutch / hatch form options
4. Register any UEFI/TPM or other Nest requirements in the provider

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
