<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Architecture: Host plane vs Nest plane</h1>
<br clear="both">

Foundational decision for cross-platform Hatchery ([epic #202](https://github.com/dustinestes/Hatchery/issues/202), [#257](https://github.com/dustinestes/Hatchery/issues/257)). Locked before Nest/provider features expand beyond the Linux + local libvirt v1 shape.

<br>

## Contents

- [Contents](#contents)
- [Decision](#decision)
- [Two planes](#two-planes)
- [One product, modular Nests](#one-product-modular-nests)
- [Requirements](#requirements)
- [Supporting a subset of Nest types](#supporting-a-subset-of-nest-types)
- [Implementation order](#implementation-order)
- [Non-goals](#non-goals)
- [Related](#related)

---

<br>

## Decision

Hatchery is **one application** with two first-class planes:

1. **Host plane** — where Hatchery runs  
2. **Nest plane** — where VMs are created and managed  

v1 shipped as Linux host + local libvirt Nest. Cross-platform work **does not** fork the product into three apps, and **does not** treat Windows/macOS as “skip Linux code.” It **decouples Nest backends** behind a shared shell so each Nest type can evolve independently and optionally.

<br>

## Two planes

| Plane | Responsibility | Examples |
|---|---|---|
| **Hatchery host** | Process, UI, Settings, SQLite, Library, hatch orchestration, Nest transport *client* | Linux, macOS, or Windows machine running Hatchery |
| **Nest** | Hypervisor control, VM lifecycle, Nest-local media/cache layout | libvirt/KVM, UTM, Hyper-V — each **local** or **remote** |

```
┌─────────────────────────────────────────┐
│           Hatchery host (any OS)        │
│  UI · Settings · DB · Library · Hatch   │
│         Nest transport client           │
└───────────────┬─────────────────────────┘
                │ factory by Nest id
     ┌──────────┼──────────┐
     ▼          ▼          ▼
 libvirt      UTM       Hyper-V
 (local/      (local/   (local/
  remote)      remote)   remote)
```

**Nest transport** (SSH default, WinRM fallback) talks to the Nest *host*. **Guest provision** (WinRM for Windows guests) stays separate — see [Nest transport](nest-transport.md).

<br>

## One product, modular Nests

| Do | Do not |
|---|---|
| Shared Flask/UI/DB/Library/orchestration | Three independent products that diverge forever |
| Each Nest type implements `BaseProvider` | Scatter `sys.platform` checks as the compatibility story |
| Select Nest via **registry** + **provider factory** | Hard-wire `LibvirtProvider` in app routes |
| Declare capabilities in the [provider matrix](providers.md) | Assume every Nest supports every action |

Libvirt-specific rules (e.g. world-readable media for `libvirt-qemu`) belong **in the libvirt Nest adapter**, not in host-plane code paths used for every Nest.

<br>

## Requirements

Split requirement reporting by plane:

| Kind | When | Examples |
|---|---|---|
| **Host-plane** | Always (app can start) | Python runtime, data dir, optional OpenSSH client for remote Nest transport |
| **Nest-local** | Only when that Nest is **local** and selected | `virsh` / `virt-install` (libvirt), `utmctl` (UTM), Hyper-V PowerShell modules |
| **Remote Nest** | Reachability via Nest transport + Nest-side tools on the Nest | SSH/WinRM to Nest; tools live on Nest, not necessarily on Hatchery host |

Tracked in [#208](https://github.com/dustinestes/Hatchery/issues/208). apt/`dpkg-query` checks are a v1 Linux convenience — not the long-term model.

<br>

## Supporting a subset of Nest types

“Support only two of three Nest hypervisors” (or only remote Hyper-V from a Linux host) is a **packaging / registry / capability** choice:

- Do not register or ship an unused provider module  
- Matrix cells stay **N/A** or **Planned**  
- No separate git fork required  

Same rule for host OS: Hatchery host must run on all three OSes in CI for the portable suite; a given deployment may only care about one host OS.

<br>

## Implementation order

Before building more Nest-specific tooling on top of hard-wired libvirt:

1. **[#207](https://github.com/dustinestes/Hatchery/issues/207)** — Nest connection registry (Settings)  
2. **[#206](https://github.com/dustinestes/Hatchery/issues/206)** — Provider factory / Nest-aware routing  
3. **[#208](https://github.com/dustinestes/Hatchery/issues/208)** — Portable host + per-provider Nest requirements  
4. Then Nest implementations: UTM (#210–#212), Hyper-V (#213–#214), remote hatch media (#215)

**Rule:** After registry + factory land, no new Nest feature should bypass them (no new hard-wired `_provider()` → libvirt-only paths).

<br>

## Non-goals

- Three separate Hatchery codebases or installers as the compatibility strategy  
- Big-bang rewrite of `LibvirtProvider` before factory/registry exist  
- Full feature parity across all Nest cells on day one (matrix tracks gaps)  
- Replacing guest WinRM with Nest transport  

<br>

## Related

| Doc / issue | Role |
|---|---|
| [Provider matrix](providers.md) | Feature × Nest capability contract |
| [Nest transport](nest-transport.md) | Control plane to Nest host |
| [Library / Nest cache](library.md) | Content planes; local vs remote ensure |
| Epic [#202](https://github.com/dustinestes/Hatchery/issues/202) | Cross-platform & remote Nests |
| [#206](https://github.com/dustinestes/Hatchery/issues/206) / [#207](https://github.com/dustinestes/Hatchery/issues/207) / [#208](https://github.com/dustinestes/Hatchery/issues/208) | Phase A foundation |

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
