<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Architecture: Controller plane vs Nest plane</h1>
<br clear="both">

Foundational decision for cross-platform Hatchery ([epic #202](https://github.com/dustinestes/Hatchery/issues/202), [#257](https://github.com/dustinestes/Hatchery/issues/257)). Locked before Nest/provider features expand beyond the Linux + local libvirt v1 shape.

<br>

## Contents

- [Contents](#contents)
- [Decision](#decision)
- [Architecture nouns](#architecture-nouns)
- [Two planes](#two-planes)
- [One product, modular Nests](#one-product-modular-nests)
- [Requirements](#requirements)
- [Supporting a subset of Nest types](#supporting-a-subset-of-nest-types)
- [Distribution north star](#distribution-north-star)
- [Implementation order](#implementation-order)
- [Non-goals](#non-goals)
- [Related](#related)

---

<br>

## Decision

Hatchery is **one application** with two first-class planes:

1. **Controller plane** — the **Hatchery Controller** (where the UI runs; controls Nest(s))  
2. **Nest plane** — hypervisors the Controller talks to for guest VMs (**Local Nest** and/or **Remote Nest**)  

v1 shipped as Linux Controller + Local Nest (libvirt). Cross-platform work **does not** fork the product into three apps, and **does not** treat Windows/macOS as “skip Linux code.” It **decouples Nest backends** behind a shared shell so each Nest type can evolve independently and optionally. A Controller may eventually have **no Local Nest** (only Remotes — [#266](https://github.com/dustinestes/Hatchery/issues/266)).

<br>

## Architecture nouns

Use these terms in UI copy, docs, issues, and agent rules. Prefer **Controller** / **Nest** over “host”.

| Noun | Definition |
|---|---|
| **Hatchery Controller** (Controller) | Device where the Hatchery UI runs; responsible for controlling the Nest(s) |
| **Nest** | Hypervisor the Controller communicates with to manage guest VMs |
| **Local Nest** | Nest on the same device as the Controller (`location=local`) — the Controller also manages guest VMs on that device |
| **Remote Nest** | Nest the Controller reaches across the control plane (`location=remote`) to manage guest VMs |

Today the registry still seeds a built-in Local Nest id `local` and forbids removing it ([#207](https://github.com/dustinestes/Hatchery/issues/207)). Making Local Nest optional (Controller with only Remote Nests) is [#266](https://github.com/dustinestes/Hatchery/issues/266).

<br>

## Two planes

| Plane | Responsibility | Examples |
|---|---|---|
| **Controller** (Controller plane) | Process, UI, Settings, SQLite, Library, hatch orchestration, Nest transport *client* | Linux, macOS, or Windows device running Hatchery |
| **Nest** (Nest plane) | Hypervisor control, VM lifecycle, Nest-local media/cache layout | libvirt/KVM, UTM, Hyper-V — each **Local Nest** or **Remote Nest** |

```
┌─────────────────────────────────────────┐
│     Hatchery Controller (any OS)        │
│  UI · Settings · DB · Library · Hatch   │
│         Nest transport client           │
└───────────────┬─────────────────────────┘
                │ factory by Nest id
     ┌──────────┼──────────┐
     ▼          ▼          ▼
 libvirt      UTM       Hyper-V
 (Local /   (Local /   (Local /
  Remote)    Remote)    Remote)
```

**Nest transport** (SSH default, WinRM fallback) talks to the Nest *machine*. **Guest provision** (WinRM for Windows guests) stays separate — see [Nest transport](nest-transport.md).

<br>

## One product, modular Nests

| Do | Do not |
|---|---|
| Shared Flask/UI/DB/Library/orchestration | Three independent products that diverge forever |
| Each Nest type implements `BaseProvider` | Scatter `sys.platform` checks as the compatibility story |
| Select Nest via **registry** + **provider factory** | Hard-wire `LibvirtProvider` in app routes |
| Declare capabilities in the [provider matrix](providers.md) | Assume every Nest supports every action |

Libvirt-specific rules (e.g. world-readable media for `libvirt-qemu`) belong **in the libvirt Nest adapter**, not in Controller-plane code paths used for every Nest.

<br>

## Requirements

Split requirement reporting by role (see [#208](https://github.com/dustinestes/Hatchery/issues/208); module `lib/requirements.py`):

| Kind | When | Examples |
|---|---|---|
| **Controller** | Always on the Controller | Python runtime, data dir; OpenSSH client when any **Remote Nest** is registered |
| **Local Nest** | Only for registered Nests with `location=local` | `virsh` / `virt-install` (libvirt), `utmctl` (UTM), Hyper-V tools — declared per provider |
| **Remote Nest** | Reachability via Nest transport; Nest-side hypervisor tools on the Nest | Controller does **not** need local `virsh` for a remote libvirt Nest |

Alerts distinguish Controller vs Local Nest missing tools. Install hints are per Controller OS (apt / brew / winget-style), not apt-only. Real Mac/Windows Nest lab validation (beyond mocked CI): [#267](https://github.com/dustinestes/Hatchery/issues/267).

<br>

## Supporting a subset of Nest types

“Support only two of three Nest hypervisors” (or only remote Hyper-V from a Linux host) is a **packaging / registry / capability** choice:

- Do not register or ship an unused provider module  
- Matrix cells stay **N/A** or **Planned**  
- No separate git fork required  

Same rule for host OS: Hatchery host must run on all three OSes in CI for the portable suite; a given deployment may only care about one host OS.

<br>

## Distribution north star

**Finish-line goal** ([#273](https://github.com/dustinestes/Hatchery/issues/273)): consumers install Hatchery with a familiar OS package manager and get only the **Hatchery Controller** — not Nest hypervisors, and not a preconfigured Nest.

```text
brew install hatchery    # or winget / apt (PPA or .deb)
→ hatchery               # start Controller
→ open UI                # empty Nest registry
→ add Nest(s); docs + validators guide readiness
```

| Ships in the consumer package | Does **not** ship or configure |
|---|---|
| Controller app (UI, API, SQLite settings, Library, hatch orchestration, Nest transport *client*) | Nest hypervisors (libvirt/KVM, UTM, Hyper-V) |
| Stable CLI entrypoint (e.g. `hatchery` / `hatchery serve`) | Pre-registered Nests or Nest credentials |
| OS-standard config + data dirs | Auto-setup of Nest machines |

Call the artifact **Controller** (not “static web UI only”) so API/DB/transport stay in scope. A fresh install with **zero Nests** is the intended empty state ([#266](https://github.com/dustinestes/Hatchery/issues/266)).

**Nest onboarding** after install is documentation plus [validators](validators.md): reachability → Nest transport → Nest-side hypervisor usability. Install hints stay per Controller OS (apt / brew / winget-style).

| Path | Role |
|---|---|
| **Consumer** | Package manager → CLI → UI. No git clone. No user-facing gunicorn. |
| **Contributor / tests** | Clone, `uv`, gunicorn (or equivalent) remain first-class for development and CI |

v1 helpers that assume a git checkout (e.g. `scripts/install-service.sh`) are a **proof-of-concept** consumer path. Long term they give way to an installable app contract and optional OS service adapters around the CLI — not checkout-coupled scripts.

**Sequencing:** lock this north star now so cross-platform work (#202) does not reintroduce clone-coupled install assumptions; ship brew / winget / apt (and optional PyPI / `pipx` middle) **after** the Controller is Nest-optional and multi-OS. Packaging formulas are implementation of [#273](https://github.com/dustinestes/Hatchery/issues/273), not a prerequisite for every Nest feature.

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
- One mega-package that installs Nest hypervisors with the Controller  
- Flatpak/Snap as the primary Local Nest distribution story (sandbox vs hypervisor access)  
- Treating clone + gunicorn as the long-term **consumer** install path (contributor path stays)  

<br>

## Related

| Doc / issue | Role |
|---|---|
| [Provider matrix](providers.md) | Feature × Nest capability contract |
| [Nest transport](nest-transport.md) | Control plane to Nest host |
| [Library / Nest cache](library.md) | Content planes; local vs remote ensure |
| [Validators](validators.md) | Pluggable checks — Nest onboarding feedback after Controller install |
| Epic [#202](https://github.com/dustinestes/Hatchery/issues/202) | Cross-platform & remote Nests |
| [#273](https://github.com/dustinestes/Hatchery/issues/273) | Distribution north star — Controller-only via OS package managers |
| [#206](https://github.com/dustinestes/Hatchery/issues/206) / [#207](https://github.com/dustinestes/Hatchery/issues/207) / [#208](https://github.com/dustinestes/Hatchery/issues/208) | Phase A foundation |
| [#266](https://github.com/dustinestes/Hatchery/issues/266) | Optional Local Nest (Controller-only) |
| [#267](https://github.com/dustinestes/Hatchery/issues/267) | Real-host Nest testing on macOS / Windows |
| [#268](https://github.com/dustinestes/Hatchery/issues/268) | Validator framework |

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
