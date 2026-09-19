# ADR-0005: Controller-only install via OS package managers

- **Status:** Accepted
- **Date:** 2026-09-19
- **Issue:** [#273](https://github.com/dustinestes/Hatchery/issues/273) (epic [#202](https://github.com/dustinestes/Hatchery/issues/202))
- **How-to:** [architecture-nests.md — Distribution north star](../architecture-nests.md#distribution-north-star)

## Context

Cross-platform Nest work can accidentally bake “clone the repo, install KVM, run gunicorn” into every path. Consumers expect familiar OS installers. Nest hypervisors are optional, OS-specific, and often remote — shipping them inside the Controller package couples the wrong planes and blocks Controller-only devices ([#266](https://github.com/dustinestes/Hatchery/issues/266)).

We needed a finish-line distribution model that:

1. Installs **Controller only** with an empty Nest registry
2. Treats Nest readiness as docs + validators, not apt/brew/winget of libvirt/UTM/Hyper-V
3. Keeps contributor/CI paths (clone, `uv`, gunicorn) valid without making them the consumer story

## Decision

1. Long-term consumer install: **apt / brew / winget** (optional PyPI / `pipx` middle) ship **Controller only**
2. Fresh install → CLI → UI with **no Nests registered**; operators add Nest(s) afterward
3. Do **not** bake Nest hypervisor packages into the core Controller install
4. Do **not** extend checkout-coupled helpers (e.g. v1 `scripts/install-service.sh`) as the product install surface
5. Contributor / tests may keep clone + `uv` + gunicorn

Ship package formulas **after** the Controller is Nest-optional and multi-OS; keep this north star on every install/run/path change.

## Consequences

**Good**

- Controller starts with zero Nests; Remote-only Controllers are first-class
- Install story matches OS norms; Nest setup stays documented and validator-guided
- Packaging work does not wait on every Nest adapter

**Neutral / follow-on**

- Optional Local Nest and empty-registry UX ([#266](https://github.com/dustinestes/Hatchery/issues/266))
- Stable CLI entrypoint (`hatchery` / `hatchery serve`) remains a packaging prerequisite

**Bad / accepted cost**

- Consumer docs must not prescribe clone + gunicorn as the primary path
- Flatpak/Snap are not the primary Local Nest story (sandbox vs hypervisor access)

## Alternatives considered

| Alternative | Why not |
|---|---|
| Mega-package with Nest hypervisors | Wrong plane; breaks Remote-only and multi-OS Controllers |
| Clone + gunicorn as consumer install | Contributor path, not consumer; checkout-coupled |
| Flatpak/Snap as primary Local Nest distribution | Sandbox conflicts with hypervisor access |
| Wait to decide until every Nest ships | Reintroduces checkout-coupled assumptions during #202 |
