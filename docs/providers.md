<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Provider and Feature Support Matrix</h1>
<br clear="both">

Living matrix of Hatchery features vs Nest **providers** (libvirt, Hyper-V, Tart, UTM) × local and remote. Update this file whenever provider capability changes.

**Architecture:** Hatchery is one app with a **Controller plane** (where the UI runs) and a **Nest plane** (hardware endpoints that hold guest VMs). A **Nest** is the machine; **providers** are adapters on that Nest ([ADR-0046](adr/0046-nest-is-hardware-multi-provider.md)). Free edition is Local Nest only ([ADR-0044](adr/0044-free-head-local-nest-only.md)); remote columns are Enterprise / Nest Agent. See [Controller plane vs Nest plane](architecture-nests.md).

<br>

## Contents

- [Contents](#contents)
- [Legend](#legend)
- [Lifecycle and Power](#lifecycle-and-power)
- [Identity, Console, and Discovery](#identity-console-and-discovery)
- [Install and Provision](#install-and-provision)
- [Nest Control Plane](#nest-control-plane)
- [Guests and Controller / Nest requirements](#guests-and-controller--nest-requirements)
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
| **libvirt local** | KVM/QEMU on the Local Nest (`LibvirtProvider`) - reference path |
| **libvirt remote** | libvirt on a Remote Nest (Enterprise / Nest Agent - not free HEAD) |
| **Hyper-V local / remote** | Windows Hyper-V (`HyperVProvider`); remote = Enterprise |
| **Tart local** | macOS Tart CLI Nest adapter ([#627](https://github.com/dustinestes/Hatchery/issues/627); free Local) |
| **UTM local / remote** | macOS UTM ([#210](https://github.com/dustinestes/Hatchery/issues/210)); remote = Enterprise |

Guest remoting is **not** Nest transport - see [Nest transport](nest-transport.md) and [Guest transport](guest-transport.md).

<br>

## Lifecycle and Power

| Feature | libvirt local | libvirt remote | UTM local | UTM remote | Hyper-V local | Hyper-V remote |
|---|---|---|---|---|---|---|
| Hatch (`create_vm`) | Works | Planned | Planned | Planned | Works (local Nest) | Planned (#215) |
| Destroy (`destroy_vm`) | Works | Planned | Planned | Planned | Works | Works |
| List / status | Works | Planned | Planned | Planned | Works | Works |
| Start / Stop / Force stop | Works | Planned | Planned | Planned | Works | Works |
| Pause / Resume | Works | Planned | Planned | Planned | Works | Works |
| Snapshot / list | Works | Planned | Planned | Planned | Works | Works |
| Revert snapshot | Works | Planned | Planned | Planned | Works | Works |
| Delete snapshot | Works | Planned | Planned | Planned | Works | Works |

Pause / Resume use hypervisor suspend (`virsh suspend` / `virsh resume` on local libvirt). Operator CLI: `hatchery vm pause|resume` ([#424](https://github.com/dustinestes/Hatchery/issues/424)). UI wiring: VMs pane (#418).

Libvirt **Destroy** best-effort force-stops the domain, ejects clutch-snapshot OS/VirtIO (and answer) media or, with no snapshot, sources under `iso_dir` / `virtio_dir`, then `virsh undefine --remove-all-storage --nvram --tpm` so UEFI NVRAM and swtpm state do not block removal and shared catalog ISOs are not deleted ([#592](https://github.com/dustinestes/Hatchery/issues/592), [#601](https://github.com/dustinestes/Hatchery/issues/601)). Before undefine, Hatchery records Nest VM dirs from domain disk paths and removes those `{…}/{vm_id}/` leftovers after undefine (ADR-0036).

Guest VM files resolve under `{nest_storage}/{vm_id}/` when Nest **nest_storage** volumes are registered (Nest detail / `extra.nest_storage`; [ADR-0039](adr/0039-nest-health-gate-and-nest-storage.md) / [#538](https://github.com/dustinestes/Hatchery/issues/538)), else the provider default path. Clutch YAML does not set a disk root ([#600](https://github.com/dustinestes/Hatchery/issues/600)). Nest **nest_cache** is the content root (Local = Controller `data_dir`; Remote = `extra.nest_cache` on Nest detail - [#215](https://github.com/dustinestes/Hatchery/issues/215) / [#607](https://github.com/dustinestes/Hatchery/issues/607)). Nest-reported sync status and Content list: [ADR-0040](adr/0040-nest-reported-nest-cache-sync.md) / [#608](https://github.com/dustinestes/Hatchery/issues/608). Nest Health host metrics (CPU/memory/disks) live in Nest Health, not this matrix ([nest-health.md](nest-health.md)).

Resource metrics (configured vs actual; Nest push vs Controller pull) are deferred under [#420](https://github.com/dustinestes/Hatchery/issues/420) until Nest remoting / job transport shape lands under epic [#202](https://github.com/dustinestes/Hatchery/issues/202).

<br>

## Identity, Console, and Discovery

| Feature | libvirt local | libvirt remote | UTM local | UTM remote | Hyper-V local | Hyper-V remote |
|---|---|---|---|---|---|---|
| IP discovery (`get_vm_ip`) | Works | Planned | Planned | Planned | Works | Works |
| UUID / rename lookup | Works | Planned | Planned | Planned | Works | Works |
| Send key (console) | Works | Planned | Planned | Planned | Planned | Planned |
| Session tags | Works | Planned | Planned | Planned | Works (VM Notes) | Works (VM Notes) |
| Guest health check | Planned | Planned | Planned | Planned | Planned | Planned |
| OOBE poweroff patch (`set_poweroff_action`) | Works | Planned | N/A | N/A | Partial (`AutomaticStopAction`) | Partial (`AutomaticStopAction`) |

Guest health check is available via operator CLI `hatchery vm health` and the VMs pane (#418). Nest connectivity check (Test Nest connection) lives in Nest transport, not the hypervisor provider.

<br>

## Install and Provision

| Feature | libvirt local | libvirt remote | UTM local | UTM remote | Hyper-V local | Hyper-V remote |
|---|---|---|---|---|---|---|
| Answer File attach (`supports_answer_file_attach`) | Works (floppy) | Planned | Planned / N/A | Planned / N/A | Works (DVD/ISO) | Planned (#215) |
| Install media cleanup (`cleanup_install_media`) | Works (#144) | Planned | Planned | Planned | Works (#144) | Planned (#215) |
| Guest WinRM provision | Works | Planned | Planned | Planned | Planned | Planned |
| Media layout (`media/iso`, VirtIO) | Works | Partial | Planned | Planned | Works (ISO; VirtIO Planned) | Planned |
| Hatch media to remote Nest | N/A | Planned | N/A | Planned | N/A | Planned (#215) |

Answer File **bytes** are Nest-agnostic; **attach** is provider-specific via Nest id → factory (`BaseProvider.supports_answer_file_attach` / `prepare_answer_file_media`). Libvirt local packs a FAT floppy with Autounattend + companions under `{nest_storage}/{vm_id}/autounattend.img` next to `disk.qcow2`. Hyper-V local packs a second DVD/ISO (``pycdlib``) as `{nest_storage}/{vm_id}/autounattend.iso` next to `disk.vhdx`. `vm_id` is a pre-minted UUID ([ADR-0036](adr/0036-pre-mint-vm-uuid-nest-storage.md)). Remote Hyper-V hatch waits on Nest-cache ensure/copy for **content** (#215); per-VM dirs stay on `nest_storage`. After `hatchery-ready`, `cleanup_install_media` ejects install/answer/VirtIO media ([ADR-0035](adr/0035-nest-install-media-lifecycle.md)). UTM depends on guest. Hatch fails early when a Clutch needs Answer File attach and the Nest cannot. See [Answer Files - Nest attach](answer-files.md#nest-attach).

Media for local libvirt uses the Hatchery data directory on the Nest (operator cache = Nest cache). Remote hatch must use Nest-local cache (or Nest-mounted share) after ensure/sync - not operator paths over WAN. See [Library and Nest cache](library.md) and [#215](https://github.com/dustinestes/Hatchery/issues/215) / [#234](https://github.com/dustinestes/Hatchery/issues/234). Guest provision stays in `lib/provision.py` regardless of Nest type.

<br>

## Nest Control Plane

Free HEAD reaches the Nest host only when it is **Local** (co-located with the Controller). Nest SSH / WinRM product transport was removed ([#620](https://github.com/dustinestes/Hatchery/issues/620), [ADR-0044](adr/0044-free-head-local-nest-only.md)). Remote Nest hierarchy is Hatchery Enterprise (Nest Agent). Historical note: [Nest transport](nest-transport.md).

| Capability | Status |
|---|---|
| Local Nest connectivity check | Works (Nests → Connections → Test Nest connection) |
| Nest connection registry (Local) | Works ([#207](https://github.com/dustinestes/Hatchery/issues/207); Nests → Connections / [ADR-0031](adr/0031-sticky-submenu-and-nests-connections.md); Local-only [#620](https://github.com/dustinestes/Hatchery/issues/620)) |
| Provider factory by Nest id | Works ([#206](https://github.com/dustinestes/Hatchery/issues/206); `lib/providers/factory.py`; refuses remote on free) |
| Remote Nest / Nest Agent | Enterprise ([#345](https://github.com/dustinestes/Hatchery/issues/345)) |

`get_provider(nest_id)` returns `LibvirtProvider` or `HyperVProvider` for a **Local** Nest. Remote Nest ids raise `UnsupportedProviderError` on free HEAD.

<br>

## Guests and Controller / Nest requirements

**Controller OS** (where the UI / CLI runs): Linux, macOS, and Windows. Portable Controller checks vs Nest tools: [#208](https://github.com/dustinestes/Hatchery/issues/208), inventory [#271](https://github.com/dustinestes/Hatchery/issues/271). README high-level summary: [What It Supports](../README.md#what-it-supports).

### Controller × Local Nest provider

| Controller OS | Local Nest providers | Free status |
|---|---|---|
| Linux | libvirt | Works (reference path) |
| Windows | Hyper-V | Works hatch / lifecycle; guest WinRM provision Planned |
| macOS | Tart, UTM | Planned (#627, #210) |

Free: one Local Nest **machine** may expose every Local provider that works there ([ADR-0046](adr/0046-nest-is-hardware-multi-provider.md)). Remote columns below remain Enterprise.

### Guest family × Local provider

| Guest family | libvirt local | Hyper-V local | Tart local | UTM local | Notes |
|---|---|---|---|---|---|
| Windows (`os: windows`) | Works | Works hatch; provision Planned | Planned | Planned | Create policy from Clutch `firmware` / `tpm` (ADR-0027). UEFI + TPM needs Nest TPM (`swtpm` on libvirt). Optional `providers.libvirt.os_variant` (#505) |
| Linux | Planned | Planned | N/A | Planned | Family values accepted in Clutch; remoting / persist under #482 / #202 |
| macOS | N/A | N/A | Planned | Planned | [#558](https://github.com/dustinestes/Hatchery/issues/558) |

### Quirk cells

| Quirk | Provider | Status | Tracking |
|---|---|---|---|
| Win11 black-screen hang after install reboot | libvirt local | Open | [#141](https://github.com/dustinestes/Hatchery/issues/141) |
| Boot-from-CD key settle / burst after Nest package upgrades | libvirt local | Open | [#171](https://github.com/dustinestes/Hatchery/issues/171) |

Add a row when a provider-specific footgun is confirmed; flip Status when fixed or documented as accepted.

Nest hypervisor tools (`virsh`, etc.) are declared on the provider (`nest_tool_specs`) and checked by the `nest_capability` validator - not as Controller requirements. On **Remote** Nests, capability is gated by Nest reachability ([#286](https://github.com/dustinestes/Hatchery/issues/286)): if the Nest is unreachable (or not yet probed), capability does not invent missing-tool Alerts. UTM / Tart imply a macOS Nest; Hyper-V implies a Windows Nest. Remote columns assume Nest transport to that OS.

<br>

## Keeping This Matrix Current

When a PR changes what a provider can do (new Nest type, local↔remote parity, or a feature gap closes):

1. Update the relevant cell(s) in this file (Works / Partial / Planned / N/A + short caveat if needed).
2. Keep README’s Controller × provider × guest summary aligned if the high-level story changed ([#216](https://github.com/dustinestes/Hatchery/issues/216)).
3. Add or close **quirk cells** when a provider-specific footgun is confirmed or fixed.
4. Agents: see [providers-and-automation](../../.cursor/rules/providers-and-automation.mdc) - capability changes must update this matrix.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
