# ADR-0027: Clutch Guest OS is family + explicit firmware/TPM

- **Status:** Accepted
- **Date:** 2026-10-03
- **Issues:** [#501](https://github.com/dustinestes/Hatchery/issues/501), Nest overlays epic [#504](https://github.com/dustinestes/Hatchery/issues/504)
- **Related:** [ADR-0024](0024-answer-files-product-model.md), [ADR-0025](0025-software-product-model.md), [ADR-0026](0026-guest-clutch-environment.md)

## Context

Clutch `os` used SKU strings (`win10`, `win11`, `server2022`, `server2025`) from when Hatchery picked Autounattend by OS. Answer Files are first-class now (ADR-0024). SKUs mainly remained for libvirt UEFI/TPM and `--os-variant`. That conflated product family with Nest create policy and blocked a clean `windows` | `linux` | `macos` contract for paths, Software, and env (#501 / #482).

Nest-native knobs (Hyper-V generation, UTM backend, virt-install pins) belong under `providers.*` overlays ([#504](https://github.com/dustinestes/Hatchery/issues/504)), not as top-level SKU strings.

## Decision

1. **`os` values:** `windows` | `linux` | `macos` only (lowercase in YAML, API, UI, and code).
2. **Portable create policy** on each VM:
   - `firmware`: `bios` | `uefi`
   - `tpm`: bool (TPM 2.0 emulator when true; libvirt today)
3. **Windows defaults** when omitted on new saves: `firmware=uefi`, `tpm=true`.
4. **Validation:** `tpm: true` requires `firmware: uefi`. Nest providers that cannot honor portable intent **fail hatch** (no silent ignore).
5. **Load-time migration** of legacy SKUs (then save rewrites the new shape):

   | Legacy `os` | Becomes |
   |---|---|
   | `win11`, `server2025` | `os: windows`, `firmware: uefi`, `tpm: true` |
   | `win10`, `server2022` | `os: windows`, `firmware: bios`, `tpm: false` |

6. **`--os-variant`:** default virt-install `win11` for `os: windows` when unset; optional pin under `providers.libvirt.os_variant` ([#505](https://github.com/dustinestes/Hatchery/issues/505)).
7. **`providers:` overlays** (stub in #501; inventories under #504): Nest-native bags under `libvirt` | `hyperv` | `utm`. Unknown keys in the active overlay fail validate. Hatch applies portable + active Nest overlay only.

## Consequences

- Answer Files, `guest_paths_for`, Software platform keys, and reserved env key off family names.
- Clutch form grows Firmware / TPM for Windows; SKU-as-create-policy wording in docs is retired.
- Full Hyper-V / UTM create wiring and libvirt inventory remain under #504–#507.

## Alternatives considered

- **Keep SKUs as `os`:** rejected; Answer File selection already decoupled; SKUs blocked family-oriented contracts.
- **Silent ignore unsupported firmware/tpm on a Nest:** rejected; fail hatch so operators see the gap.
