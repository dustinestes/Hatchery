# ADR-0046: Nest is hardware; many Local providers on one Nest

- **Status:** Accepted
- **Date:** 2026-11-14
- **Issues:** [#629](https://github.com/dustinestes/Hatchery/issues/629), [#628](https://github.com/dustinestes/Hatchery/issues/628), epic [#202](https://github.com/dustinestes/Hatchery/issues/202)
- **Related:** [ADR-0003](0003-nest-registry-provider-factory.md), [ADR-0042](0042-open-core-public-and-enterprise-tier.md), [ADR-0044](0044-free-head-local-nest-only.md)
- **How-to:** [architecture-nests.md](../architecture-nests.md), [providers.md](../providers.md), [north-star.md](../north-star.md)

## Context

Early free HEAD modeled a Nest registry row as roughly one `provider_type` (libvirt-era), and entitlements prose `max_nests = 1` was easy to read as “one hypervisor.” Product intent from open-core triage is different:

- A **Nest** is one hardware endpoint (desktop / laptop / server) where Clutches hatch.
- **Providers** (libvirt, Hyper-V, Tart, UTM, later others) are adapters **on** that Nest.
- Free must not monetize how an operator uses hypervisors already on their machine.
- Enterprise `max_nests` counts Nest **machines** (Local Controller host + Remote Agent hosts), not Local provider count.
- Nest Agent should reuse the same Local provider adapters per Nest OS (parity), not invent a second hypervisor matrix.

Code today still forces Nest id `local` with a single `provider_type` per row ([ADR-0044](0044-free-head-local-nest-only.md) / #620). That remains Local-only (no Remote Nest on free); it does **not** yet express “one Nest, many providers.”

## Decision

1. **Nest = hardware endpoint.** Branding and docs use Nest for the machine, not for a single hypervisor product name.
2. **Providers are first-class adapters on a Nest.** Controller OS must not imply a single Nest provider. macOS may run Tart and UTM on the same Nest; Windows may later add VirtualBox, etc., without renaming Nest.
3. **Free edition:** one Local Nest machine (the Controller host when used as Nest) may expose every Local provider that works there. Free still refuses Remote Nest / Nest Agent product ([ADR-0044](0044-free-head-local-nest-only.md)).
4. **`max_nests`:** counts Nest **machines**. Free `max_nests = 1` means one Local Nest machine, not “only one of libvirt/Hyper-V/Tart/UTM.” Enterprise capacity adds Remote Nest machines.
5. **Factory stays provider-typed** ([ADR-0003](0003-nest-registry-provider-factory.md)). Schema/UX must evolve so a Nest owns zero or more providers; do not hard-wire `sys.platform` → one adapter outside validators/UX hints.
6. **Agent parity:** for a Nest OS, Remote Nest Agent jobs use the same provider adapters proven Locally for that OS.

## Consequences

**Good**

- Aligns branding with empowerment: Hatchery orchestrates; it does not landlord Local hypervisors.
- Clear paid boundary: hierarchy across machines, not unlocking a second Local provider.
- Support matrix (#216) tracks Controller × **provider** × guest, not “the macOS Nest type.”

**Neutral / follow-on**

- Implementation PR(s) must lift “one Nest row = one `provider_type`” toward Nest-with-providers (exact schema TBD). Until then, operators may still switch `provider_type` on id `local` as a stopgap.
- Amend operator reading of [ADR-0042](0042-open-core-public-and-enterprise-tier.md) free/`max_nests` lines via this ADR (do not renumber 0042).
- Tart and UTM are both first-class free macOS Local providers (hard goals, soft calendar gates).

**Bad / accepted cost**

- Temporary docs/code mismatch until the registry shape lands.
- Multi-provider Nest Health / storage / hatch targeting UX gets harder (which provider hatches this Clutch?) - resolve in provider-settings / Clutch Nest binding follow-ons (#504 family).

## Alternatives

| Alternative | Why not |
|---|---|
| Nest = one hypervisor; Tart and UTM are two Nest seats | Monetizes owner hardware; fights Nest branding |
| Free allows unlimited Remote Nest machines | Conflicts with open-core hierarchy ([ADR-0042](0042-open-core-public-and-enterprise-tier.md)) |
| OS = single provider forever | Footguns expansion; false on macOS today |
