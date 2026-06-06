<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Error Handling</h1>
<br clear="both">

How Hatchery surfaces errors — HTTP codes, VM operation failures, and UI error display.

<br>

## Contents

- [Contents](#contents)
- [Principles](#principles)
- [HTTP Error Codes](#http-error-codes)
- [VM Operation Errors](#vm-operation-errors)
- [Provisioning Errors](#provisioning-errors)

---

<br>

## Principles

- Errors always surface in the UI — never silently swallowed into server logs only
- VM operation failures include the underlying `virsh` / `virt-install` stderr so the user knows what went wrong
- Provisioning failures are non-fatal — the VM exists and is accessible even if post-install steps partially fail

---

<br>

## HTTP Error Codes

| Code | Meaning |
|---|---|
| `400` | Bad request — invalid form input or missing required field |
| `404` | VM not found — the named VM does not exist in the brood |
| `409` | Conflict — operation not valid for current VM state (e.g. start on a running VM) |
| `500` | Internal error — unexpected failure in a VM operation; includes the underlying error message |

---

<br>

## VM Operation Errors

VM operations (`virt-install`, `virsh start`, `virsh destroy`, etc.) are run via subprocess. If the subprocess exits non-zero, the error includes:
- The command that was run
- The exit code
- The full stderr output

This information is returned in the API response and displayed in the UI.

---

<br>

## Provisioning Errors

Post-install provisioning over WinRM can fail if:
- WinRM is not yet enabled on the guest (install not complete)
- The guest IP is not reachable from the host
- WinRM credentials are incorrect

Provisioning failures do not destroy the VM. The VM remains accessible and the user can re-trigger provisioning from the manage page, or connect manually via RDP.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Where environments hatch</div>
<br clear="both">
