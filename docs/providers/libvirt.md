<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>libvirt</h1>
<br clear="both">

Libvirt Nest provider notes and Clutch YAML inventory under `providers.libvirt` ([#505](https://github.com/dustinestes/Hatchery/issues/505); epic [#504](https://github.com/dustinestes/Hatchery/issues/504)).

**Rules (locked in #504):** portable guest intent stays top-level (`os`, `firmware`, `tpm`, resources, Answer File, env). Libvirt-native knobs live only under `providers.libvirt`. Unknown keys under that bag fail validate. Hatch on a libvirt Nest applies portable intent + this overlay only.

Matrix hub: [Provider support matrix](README.md). Schema: `LibvirtProviderSettings` in [`lib/clutch.py`](../../lib/clutch.py). Create wiring: [`lib/providers/libvirt.py`](../../lib/providers/libvirt.py) ([#635](https://github.com/dustinestes/Hatchery/issues/635)).

<br>

## Contents

- [Contents](#contents)
- [Legend](#legend)
- [Portable intent → libvirt](#portable-intent--libvirt)
- [Inventory](#inventory)
- [Create defaults (when overlay keys omitted)](#create-defaults-when-overlay-keys-omitted)
- [Draft YAML](#draft-yaml)
- [Non-goals (v1 overlay)](#non-goals-v1-overlay)
- [UI surface note](#ui-surface-note)
- [Implementation follow-ons](#implementation-follow-ons)
- [Related](#related)

---

<br>

## Legend

| Column | Meaning |
|---|---|
| **Key** | YAML path under `providers.libvirt` unless marked portable |
| **Type** | Value shape |
| **Default** | When omitted |
| **Plane** | `portable` (top-level) vs `overlay` (`providers.libvirt`) vs `hardcoded` |
| **When** | `create` only vs `create+update` (update = post-define domain change; rare in v1) |
| **Local / Remote** | Local Nest notes; Remote = Enterprise Nest Agent parity target |
| **UI** | `clutch-advanced` / `nest-default` / `never` (see [UI surface note](#ui-surface-note)) |
| **Status** | `shipped` / `planned` / `wont` |

<br>

## Portable intent → libvirt

| Portable field | Libvirt mapping today | Overlay override? |
|---|---|---|
| `os: windows` | `--os-variant` defaults to `win11` when unset | `providers.libvirt.os_variant` pins |
| `os: linux` / `macos` | `--os-variant generic` until Linux/macOS hatch depth | pin via `os_variant` |
| `firmware: uefi` | `--boot uefi` | no overlay; portable only ([ADR-0027](../adr/0027-clutch-guest-os-family-firmware-tpm.md)) |
| `firmware: bios` / omit | no `--boot uefi` | portable only |
| `tpm: true` | `--tpm emulator,model=tpm-crb,version=2.0` | TPM model/version overlay is **wont** for v1 (portable on/off only) |
| `vcpus` / `ram_gb` / `disk_gb` | `--vcpus` / `--memory` MiB / disk `size=` | no libvirt overlay aliases |
| `drivers` (portable) | extra `--disk …,device=cdrom` when set | reshape locked in [drivers.md](../drivers.md) ([#508](https://github.com/dustinestes/Hatchery/issues/508)) |
| `answer_file` | floppy attach when Windows | Nest attach capability, not overlay |

<br>

## Inventory

| Key | Type | Default | Plane | When | Local / Remote | UI | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| `os_variant` | string | Windows → `win11`; else `generic` | overlay | create | Local Works; Remote Planned | clutch-advanced | shipped | virt-install `--os-variant`; must match Nest `osinfo` database |
| *(portable)* `firmware` | `bios` \| `uefi` | unset → BIOS-ish | portable | create | Local Works; Remote Planned | clutch form | shipped | maps to `--boot uefi` only |
| *(portable)* `tpm` | bool | false / unset | portable | create | needs `swtpm` on Nest | clutch form | shipped | fixed emulator model today |
| `network` | string | `default` | overlay | create | Local libvirt network name; Remote same on Nest | clutch-advanced | shipped | `#635`; omit → `network=default` |
| `network_model` | string | virt-install default | overlay | create | e.g. `virtio` | clutch-advanced | shipped | `#635`; `--network …,model=` when set |
| `disk_bus` | string | virt-install default | overlay | create | e.g. `virtio` | clutch-advanced | shipped | `#635`; guest disk bus only; not catalog CDROM |
| `graphics` | string | `spice` | overlay | create | Local SPICE; Remote display TBD | clutch-advanced | shipped | `#635`; omit → `--graphics spice` |
| `video` | string | virt-install default | overlay | create | e.g. `qxl` / `virtio` | clutch-advanced | planned | often paired with graphics |
| `cpu_model` | string | host default | overlay | create | host-passthrough caution | clutch-advanced | planned | `--cpu` / model |
| `cpu_topology` | object | unset | overlay | create | sockets/cores/threads | clutch-advanced | planned | only if needed beyond `vcpus` |
| `machine` | string | Nest qemu default | overlay | create | e.g. `q35` | clutch-advanced | shipped | `#635`; `--machine` when set |
| `chipset` | string | implied by machine | overlay | create | prefer `machine` alone | never | wont | use `machine`; avoid duplicate knobs |
| `boot_order` | list/string | virt-install default | overlay | create | cdrom-first install | clutch-advanced | planned | careful with post-install |
| `uefi_loader` / `nvram_template` | path | Nest defaults | overlay | create | Nest absolute paths | nest-default | planned | Remote: Nest-local paths only |
| `tpm_model` | string | `tpm-crb` + 2.0 | overlay | create | — | never | wont | portable `tpm` is enough for v1 |
| `rng` | bool/object | off | overlay | create | `/dev/urandom` backend | clutch-advanced | planned | optional entropy |
| `watchdog` | bool/object | off | overlay | create | — | clutch-advanced | planned | low priority |
| *(portable)* `drivers` | path/basename | unset | portable | create | Windows + libvirt | clutch form | planned | See [drivers.md](../drivers.md); not a `providers.libvirt` key |

<br>

## Create defaults (when overlay keys omitted)

| Behavior | Value |
|---|---|
| Network | `network=default` (override via `network` / `network_model`) |
| Graphics | `spice` (override via `graphics`) |
| Disk format | `qcow2` under `{nest_storage}/{vm_id}/disk.qcow2` (`disk_bus` optional) |
| Install CDROM | `--cdrom` from portable `os_media` |
| UUID | pre-minted `vm_id` (`--uuid`) |
| Console | `--noautoconsole` |

Destroy / lifecycle are provider methods, not Clutch overlay keys ([ADR-0047](../adr/0047-destroy-removes-nest-vm-storage.md)).

<br>

## Draft YAML

```yaml
vms:
  - name: win11-dev
    os: windows
    firmware: uefi
    tpm: true
    vcpus: 4
    ram_gb: 8
    disk_gb: 80
    os_media: Win11_English_x64.iso
    drivers: virtio-win.iso          # portable; see docs/drivers.md
    answer_file: windows/autounattend.xml
    providers:
      libvirt:
        os_variant: win11
        network: default
        network_model: virtio
        disk_bus: virtio
        graphics: spice
        machine: q35
```

Minimal (overlay optional):

```yaml
vms:
  - name: win11-dev
    os: windows
    firmware: uefi
    tpm: true
    # …resources + media…
    # providers.libvirt omitted → os_variant defaults to win11
```

<br>

## Non-goals (v1 overlay)

- Controller **Settings → Libvirt** (or Hyper-V / UTM / Tart) panes - not designed; Nest defaults IA is follow-on
- Silent ignore of unknown `providers.libvirt` keys (must fail validate)
- Applying `providers.hyperv` / `providers.utm` when hatching on libvirt
- Exposing every virt-install flag (channel, smartcard, redirection, balloon tuning, hugepages, NUMA, …)
- Duplicate portable fields under the overlay (`firmware` / `tpm` / `vcpus` / `drivers` aliases)
- Post-create live domain XML edit as the primary settings path (v1 is create-time)
- Storing Nest absolute UEFI paths in Clutches meant to be Nest-portable without Nest defaults

<br>

## UI surface note

| UI value | Meaning |
|---|---|
| `clutch-advanced` | Clutch Build/Edit (or YAML-only) on the VM row when Nest is libvirt-capable |
| `nest-default` | Future Nest-plane default (Nest detail / provider defaults) - **not designed yet** |
| `never` | Hard-coded, docs-only, or wont-support |

Drivers / VirtIO field visibility by Nest × guest OS: [drivers.md](../drivers.md) ([#508](https://github.com/dustinestes/Hatchery/issues/508)).

<br>

## Implementation follow-ons

- [#635](https://github.com/dustinestes/Hatchery/issues/635) - first-cut overlay keys (`network`, `network_model`, `disk_bus`, `graphics`, `machine`) - **this doc / schema**
- Later inventory rows still planned: `video`, `cpu_model`, `boot_order`, UEFI Nest paths, …
- Drivers portable key: [drivers.md](../drivers.md) / [#637](https://github.com/dustinestes/Hatchery/issues/637)

Do **not** block on Nest-default UI or Settings panes.

<br>

## Related

- Epic [#504](https://github.com/dustinestes/Hatchery/issues/504) - Clutch Nest provider settings
- [#508](https://github.com/dustinestes/Hatchery/issues/508) - Drivers media field planning
- [#506](https://github.com/dustinestes/Hatchery/issues/506) / [#507](https://github.com/dustinestes/Hatchery/issues/507) - Hyper-V / UTM inventories (later waves)
- [ADR-0027](../adr/0027-clutch-guest-os-family-firmware-tpm.md) - portable firmware / TPM
- [Provider matrix](README.md)

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
