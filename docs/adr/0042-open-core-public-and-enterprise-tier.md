# ADR-0042: Open-core - public Hatchery and private Enterprise tier

- **Status:** Accepted
- **Date:** 2026-10-21
- **Issues:** [#614](https://github.com/dustinestes/Hatchery/issues/614); sequencing [#345](https://github.com/dustinestes/Hatchery/issues/345), [#609](https://github.com/dustinestes/Hatchery/issues/609)
- **Related:** [ADR-0005](0005-controller-only-package-distribution.md), [ADR-0014](0014-optional-local-nest.md), [ADR-0021](0021-controller-embeddable-operator-plane.md); epic [#202](https://github.com/dustinestes/Hatchery/issues/202)

## Context

Hatchery’s battle-tested product path is still **Local Nest + Windows guests (libvirt)**. Much of `main` is mid-flight toward Remote Nests, Hyper-V/UTM parity, Nest Agent, and fleet hierarchy. Those are valuable designs in history, but they are **not** a fully shipped enterprise product.

We want an Artifactory-OSS-shaped free edition: a real product that **works in a vacuum** for home labs and builders, while businesses that need multi-Nest hierarchy pay for a commercial tier. Nights and weekends spent on fleet remoting should not land as MIT-by-default forever.

## Decision

1. **Product brand stays Hatchery.** Enterprise is a **purchase tier**, not a second product name. Do not use `hatchery-pro`, `hatchery-paid`, or other alternate brands. Gradation inside paid is **modular SKUs**, not more repos.

2. **Two git homes only:**
   - **Public** [`dustinestes/Hatchery`](https://github.com/dustinestes/Hatchery) - MIT; free / local edition; full history kept (no strip/rewrite).
   - **Private** [`dustinestes/hatchery-enterprise`](https://github.com/dustinestes/hatchery-enterprise) - commercial license; Python package that **layers** on a pinned public Hatchery (not a full-app fork).

3. **Free edition (north star):** Controller on Linux / macOS / Windows; **one Local Nest** when that provider works; portable Clutch/media/content share between independent Controllers. Explicitly **not** one Controller webbing many Remote Nests.

4. **Paid edition (hierarchy):** Nest Agent, Remote Nest enroll/capacity, remote nest_cache ensure/pull, content origin, fleet Library depth, later SSO/RBAC/audit as packs. Implement new hierarchy value in the private package.

5. **Entitlements (commercial package):** signed license file (JWT/JSON) on Controller `data_dir`; modular `features` packs + numeric `max_nests` (never unlimited). Controller seat is the majority fee; nest capacity is an add-on with bulk step-down pricing. Layered trust: license → Controller-issued Nest credentials → optional soft Controller→portal renewal report. Nest Agents phone the Controller only. Authorize / Pending / Enrolled / Unenroll; external Agent imaging is first-class. Free tier `max_nests = 1` Local-only.

6. **Honesty:** Mid-flight Remote/UTM/Tart/fleet code in history does not make free “taking away” a finished enterprise suite. Document free vs paid clearly so docs do not promise unfinished hierarchy as free.

7. **Piracy:** Acceptable loss for determined self-host patching. Prefer private source for paid modules + signed license + support/updates. No kernel DRM; no mandatory always-online Nest→cloud license checks.

8. **Production paid gate (before selling):** Stripe (or MoR) + license mint + delivery (e.g. hatchery.app). Offline license file remains first-class. Not required to land this ADR or the private repo scaffold.

9. **GitHub ownership:** Bootstrap under personal `dustinestes` for portfolio attribution. Org transfer is optional later; not required for open-core.

10. **Sequencing:** After this ADR: Nest Agent (#345) in private; then #609 as first Agent job type. No SSH one-shot #609.

## Consequences

**Good**

- Clear free/paid boundary and brand continuity
- Public trust (history + ADR) without publishing new hierarchy source as MIT
- Modular SKUs without repo sprawl
- Air-gapped labs remain viable (offline license file)

**Neutral / follow-on**

- Public extension hooks so the enterprise package can register packs without forking the Controller
- Audit public issues/code for surfaces that belong in enterprise ([hatchery-enterprise](https://github.com/dustinestes/hatchery-enterprise) tracking)
- Entitlement stub and Stripe/mint before first paid customer

**Bad / accepted cost**

- Dual-repo developer workflow (mitigated by multi-root Cursor workspace)
- Already-published MIT blobs remain MIT if recovered from history

## Alternatives considered

| Alternative | Why not |
|---|---|
| Strip/rewrite public history | Dishonest; destroys design narrative; unnecessary for mid-flight hierarchy |
| Single private product (no free OSS) | Conflicts with Artifactory-OSS-shaped personal/lab story |
| Public monorepo mixed licenses | Weak if goal is paid source not published free |
| Many paid repos / hatchery-pro naming | Brand and SKU sprawl; enterprise is a tier of Hatchery |
| Enterprise license-vendor as day-one foundation | Cost/complexity vs maybe-never fleet customers; offline JWT + Stripe mint is enough early |
| Org migration required before open-core | Portfolio attribution; transfer later if needed |
