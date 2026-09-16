<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Provider and Feature Support Matrix</h1>
<br clear="both">

Living matrix of Hatchery features vs Nest providers (libvirt, UTM, Hyper-V) × local and remote. Update this file whenever provider capability changes.

**Architecture:** Hatchery is one app with a **Host plane** (where the app runs) and a **Nest plane** (where VMs live). Nest backends are modular first-class adapters — see [Host plane vs Nest plane](architecture-nests.md).

<br>

## Contents

- [Contents](#contents)
- [Legend](#legend)
- [Lifecycle and Power](#lifecycle-and-power)
- [Identity, Console, and Discovery](#identity-console-and-discovery)
- [Install and Provision](#install-and-provision)
- [Nest Control Plane](#nest-control-plane)
- [Guests and Host Requirements](#guests-and-host-requirements)
- [Keeping This Matrix Current](#keeping-this-matrix-current)

---

<br>

## Legend

| Cell | Meaning |
|---|---|
| **Works** | Implemented and expected to work in current `main` |
| **Partial** | Present with caveats (see notes under the table) |
| **Planned** | Tracked for epic [#202](https://github.com/dustinestes/Hatchery/issues/202); not usable yet |
| **N/A** | Not applicable for that Nest shape |

<br>

| Column | Nest |
|---|---|
| **libvirt local** | KVM/QEMU on the same machine as Hatchery (`LibvirtProvider`) — v1 |
| **libvirt remote** | libvirt Nest reached over Nest transport |
| **UTM local / remote** | macOS UTM Nest ([#210](https://github.com/dustinestes/Hatchery/issues/210)–[#212](https://github.com/dustinestes/Hatchery/issues/212)) |
| **Hyper-V local / remote** | Windows Hyper-V Nest ([#213](https://github.com/dustinestes/Hatchery/issues/213); stub `lib/providers/hyperv.py`) |

Guest WinRM provisioning is **not** Nest transport — see [Nest transport](nest-transport.md).

<br>

## Lifecycle and Power

| Feature | libvirt local | libvirt remote | UTM local | UTM remote | Hyper-V local | Hyper-V remote |
|---|---|---|---|---|---|---|
| Hatch (`create_vm`) | Works | Planned | Planned | Planned | Planned | Planned |
| Cull (`destroy_vm`) | Works | Planned | Planned | Planned | Planned | Planned |
| List / status | Works | Planned | Planned | Planned | Planned | Planned |
| Start / Stop / Force stop | Works | Planned | Planned | Planned | Planned | Planned |
| Pause / Resume | Planned | Planned | Planned | Planned | Planned | Planned |
| Snapshot / list | Works | Planned | Planned | Planned | Planned | Planned |
| Revert snapshot | Works | Planned | Planned | Planned | Planned | Planned |
| Delete snapshot | Works | Planned | Planned | Planned | Planned | Planned |

Pause and Resume are product language only today (status may show paused from libvirt); there is no provider API or UI action yet.

<br>

## Identity, Console, and Discovery

| Feature | libvirt local | libvirt remote | UTM local | UTM remote | Hyper-V local | Hyper-V remote |
|---|---|---|---|---|---|---|
| IP discovery (`get_vm_ip`) | Works | Planned | Planned | Planned | Planned | Planned |
| UUID / rename lookup | Works | Planned | Planned | Planned | Planned | Planned |
| Send key (console) | Works | Planned | Planned | Planned | Planned | Planned |
| Session tags | Works | Planned | Planned | Planned | Planned | Planned |
| Guest health check | Planned | Planned | Planned | Planned | Planned | Planned |
| OOBE poweroff patch (`set_poweroff_action`) | Works | Planned | N/A | N/A | Planned | Planned |

Guest health check is tracked in [#14](https://github.com/dustinestes/Hatchery/issues/14). Nest connectivity check (Test Nest connection) lives in Nest transport, not the hypervisor provider.

<br>

## Install and Provision

| Feature | libvirt local | libvirt remote | UTM local | UTM remote | Hyper-V local | Hyper-V remote |
|---|---|---|---|---|---|---|
| Windows answer files (Autounattend) | Works | Planned | Planned | Planned | Planned | Planned |
| Guest WinRM provision | Works | Planned | Planned | Planned | Planned | Planned |
| Media layout (`media/iso`, VirtIO) | Works | Partial | Planned | Planned | Planned | Planned |
| Hatch media to remote Nest | N/A | Planned | N/A | Planned | N/A | Planned |

Media for local libvirt uses the Hatchery data directory on the Nest (operator cache = Nest cache). Remote hatch must use Nest-local cache (or Nest-mounted share) after ensure/sync — not operator paths over WAN. See [Library and Nest cache](library.md) and [#215](https://github.com/dustinestes/Hatchery/issues/215) / [#234](https://github.com/dustinestes/Hatchery/issues/234). Guest provision stays in `lib/provision.py` regardless of Nest type.

<br>

## Nest Control Plane

How Hatchery reaches the Nest host (not the guest). Module: [`lib/nest_transport.py`](../../lib/nest_transport.py). Detail: [Nest transport](nest-transport.md).

| Capability | Status |
|---|---|
| SSH Nest transport (key **reference**) | Works (wired via Nest registry [#207](https://github.com/dustinestes/Hatchery/issues/207)) |
| WinRM Nest transport fallback | Works (same registry; passwords session-only until [#110](https://github.com/dustinestes/Hatchery/issues/110)) |
| Nest connectivity check | Works (Settings → Nests → Test Nest connection) |
| Nest SSH identity expiry alerts | Works ([Nest SSH identity expiry](nest-key-expiry.md)) |
| Nest connection registry / Settings | Works ([#207](https://github.com/dustinestes/Hatchery/issues/207); Settings → Nests) |
| Provider factory by Nest id | Planned ([#206](https://github.com/dustinestes/Hatchery/issues/206)) |

Today Hatchery still hard-wires local libvirt for VM ops on local Nests; remote inventory waits on the provider factory. Transport + registry are ready for remote Nests.

<br>

## Guests and Host Requirements

| Guest / host | libvirt local | Notes |
|---|---|---|
| Windows 10 / 11 / Server 2022 / 2025 | Works | Win11 / Server 2025 need UEFI + TPM (`swtpm`) |
| Linux guests | Planned | Phase D of epic #202 |
| Hatchery host OS | Ubuntu (v1) | macOS / Windows Hatchery hosts: [#203](https://github.com/dustinestes/Hatchery/issues/203), [#25](https://github.com/dustinestes/Hatchery/issues/25), [#208](https://github.com/dustinestes/Hatchery/issues/208) |

UTM implies a macOS Nest; Hyper-V implies a Windows Nest. Remote columns assume Nest transport to that OS.

<br>

## Keeping This Matrix Current

When a PR changes what a provider can do (new Nest type, local↔remote parity, or a feature gap closes):

1. Update the relevant cell(s) in this file (Works / Partial / Planned / N/A + short caveat if needed).
2. Keep README’s guest/provider summary aligned if the high-level story changed.
3. Agents: see [providers-and-automation](../../.cursor/rules/providers-and-automation.mdc) — capability changes must update this matrix.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
