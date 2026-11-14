<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Guest Drivers media field</h1>
<br clear="both">

Planning decisions for the Clutch install-time **Drivers** media field ([#508](https://github.com/dustinestes/Hatchery/issues/508); epic [#504](https://github.com/dustinestes/Hatchery/issues/504)). Replace the Windows-centric top-level VirtIO-named field with a Nest-agnostic portable key.

Portable create field (sibling of [Answer Files](answer-files.md)), not a Nest provider. Matrix hub: [Provider support matrix](providers/README.md). Libvirt provider doc: [libvirt](providers/libvirt.md).

<br>

## Contents

- [Contents](#contents)
- [Locked decisions](#locked-decisions)
- [Nest × guest OS matrix](#nest--guest-os-matrix)
- [YAML shape](#yaml-shape)
- [Media catalog](#media-catalog)
- [UI copy](#ui-copy)
- [Create vs post-boot](#create-vs-post-boot)
- [Non-goals](#non-goals)
- [Implementation follow-ons](#implementation-follow-ons)
- [Related](#related)

---

<br>

## Locked decisions

1. **Portable intent key: `drivers`** (optional string: Nest media basename or relative path). Same Nest-agnostic idea as `os_media`: “attach this install-time drivers/tools ISO when the Nest can.”
2. **No load-time compatibility for the old VirtIO-named Clutch field.** Impl replaces that field with `drivers` only (unused in the wild; do not WARN-migrate).
3. **No Nest-specific YAML aliases for v1** (`providers.libvirt.virtio_iso`, `providers.utm.guest_tools_iso`, …). Attach semantics stay in the provider; the Clutch only names the media. Provider docs may still document how attach works ([libvirt](providers/libvirt.md)).
4. **Show / hide by Nest × guest OS** (table below). Hidden means omit from Clutch form; if YAML still sets `drivers` and the Nest cannot attach, **fail hatch** with a clear error (same spirit as Answer File attach / Hyper-V reject today).
5. **UI label: Drivers** everywhere; Nest-specific help text when Nest type is known (VirtIO win ISO vs UTM guest tools, etc.).
6. **v1 is create-time CDROM/ISO attach only.** Post-create extra ISO attach stays [#122](https://github.com/dustinestes/Hatchery/issues/122).

<br>

## Nest × guest OS matrix

| Nest provider | Guest `os` | Show Drivers? | Media role | Missing media |
|---|---|---|---|---|
| libvirt | windows | Yes | VirtIO Windows drivers ISO (create CDROM) | Optional omit; if set and missing → fail hatch |
| libvirt | linux | No (v1) | — | If set → fail hatch (“not supported for linux on libvirt yet”) |
| libvirt | macos | No | N/A | If set → fail hatch |
| Hyper-V | windows | No | Synthetic devices; no VirtIO ISO attach today | If set → fail hatch (current behavior) |
| Hyper-V | linux / macos | No | — | If set → fail hatch |
| UTM | windows | Yes (when UTM hatch lands) | Guest tools / drivers ISO | Optional omit; if set and missing → fail hatch |
| UTM | linux | Deferred (#507) | Guest tools if applicable | TBD in UTM inventory |
| UTM | macos | Deferred (#507) | — | TBD |
| Tart | any | Deferred (#627) | — | TBD |

“Show” is Clutch Build/Edit visibility when the hatch Nest (or selected Nest) is that provider. Clutches remain Nest-agnostic until hatch: YAML may carry `drivers` for a Nest that will use it; a Nest that cannot attach must fail closed.

<br>

## YAML shape

```yaml
vms:
  - name: win11-dev
    os: windows
    firmware: uefi
    tpm: true
    os_media: Win11_English_x64.iso
    drivers: virtio-win.iso          # portable intent
    answer_file: windows/autounattend.xml
    providers:
      libvirt:
        os_variant: win11
```

| Case | Behavior |
|---|---|
| `drivers` set | Attach when Nest×OS supports; else fail hatch |
| Empty / omit | No drivers ISO attach |

<br>

## Media catalog

| Nest | Catalog today | Notes |
|---|---|---|
| libvirt Local | `{nest_cache}/media/virtio/` (Controller `data_dir` when Local) | Keep directory name for now; UI Media → VirtIO pane continues to inventory this pool |
| Hyper-V | N/A for Drivers field | — |
| UTM | Same Nest `media/` tree; prefer clear basenames (guest-tools ISO) until #507 may split catalogs | Do not invent a second Operator Settings catalog in this planning |

Future optional rename to `media/drivers/` is a Media pane follow-on, not required to ship `drivers` YAML.

<br>

## UI copy

| Surface | Copy |
|---|---|
| Field label | **Drivers** |
| Placeholder | Select drivers / guest tools ISO (optional) |
| Help (libvirt + windows) | VirtIO drivers ISO attached at create for Windows guests on libvirt. |
| Help (UTM + windows) | Guest tools / drivers ISO attached at create when UTM hatch supports it. |
| Help (hidden Nest/OS) | Field hidden; do not show VirtIO branding on Hyper-V or non-Windows libvirt rows. |
| Media pane | Keep **VirtIO** inventory title until a Media rename follow-on; Clutch field is **Drivers**. |

<br>

## Create vs post-boot

| Phase | v1 |
|---|---|
| Create attach | Yes - provider CDROM/ISO at hatch |
| Post-ready cleanup | Existing install-media cleanup ejects drivers media with OS/answer ([ADR-0035](adr/0035-nest-install-media-lifecycle.md)) |
| Post-create attach / hotplug | Out of scope - [#122](https://github.com/dustinestes/Hatchery/issues/122) |
| Guest Software packages for VirtIO/tools | Separate Software plane ([ADR-0025](adr/0025-software-product-model.md)); not this field |

<br>

## Non-goals

- Nest-specific Clutch keys for the same media (`providers.libvirt.virtio_iso` duplicate of `drivers`)
- Load-time aliases or WARN migration for the old VirtIO-named field
- Presenting Drivers as required for Windows on every Nest
- Hyper-V VirtIO ISO attach in v1
- Renaming the Media → VirtIO pane in the same PR as the Clutch field rename
- Controller Settings page for Drivers catalogs

<br>

## Implementation follow-ons

- [#637](https://github.com/dustinestes/Hatchery/issues/637) - replace Clutch field with portable `drivers`; UI label/visibility; provider attach + fail-closed

Also refresh [libvirt](providers/libvirt.md) examples as that lands (already aligned in planning).

<br>

## Related

- Epic [#504](https://github.com/dustinestes/Hatchery/issues/504)
- [#505](https://github.com/dustinestes/Hatchery/issues/505) / [libvirt](providers/libvirt.md)
- [#506](https://github.com/dustinestes/Hatchery/issues/506) Hyper-V inventory
- [#507](https://github.com/dustinestes/Hatchery/issues/507) UTM inventory
- [#122](https://github.com/dustinestes/Hatchery/issues/122) additional ISO attach
- [#501](https://github.com/dustinestes/Hatchery/issues/501) / [ADR-0027](adr/0027-clutch-guest-os-family-firmware-tpm.md) portable OS family
- [Answer Files](answer-files.md) - install-time templates (sibling portable plane)

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
