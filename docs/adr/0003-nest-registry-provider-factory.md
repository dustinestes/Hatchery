# ADR-0003: Nest registry + provider factory (no hard-wired libvirt)

- **Status:** Accepted
- **Date:** 2026-09-19
- **Issues:** [#206](https://github.com/dustinestes/Hatchery/issues/206), [#207](https://github.com/dustinestes/Hatchery/issues/207) (epic [#202](https://github.com/dustinestes/Hatchery/issues/202))
- **How-to:** [architecture-nests.md](../architecture-nests.md), [providers.md](../providers.md)

## Context

Hatchery must run as a **Controller** on Linux, macOS, and Windows and manage **Local** and **Remote** Nests across libvirt/KVM, UTM, and Hyper-V. Early code treated Nest as a dead `"local"` string and hard-wired `LibvirtProvider` through `_provider()`, which cannot express remoting, other hypervisors, or Controller-only installs.

We needed a shape that:

1. Lets operators register zero or more Nest connections in Settings
2. Resolves every list / hatch / power / snapshot / IP path by Nest id → `BaseProvider`
3. Keeps hypervisor differences in Nest adapters - not forked product apps

## Decision

1. Persist Nest connections in a **registry** (Settings → Nests; SQLite `nests` table)
2. Route Nest work through a **provider factory**: Nest id → provider type × location → `BaseProvider` implementation
3. After registry + factory land, **no new Nest feature may bypass them** (no new hard-wired `_provider()` → libvirt-only paths)
4. Nest **transport** (Controller → Nest host) stays separate from **guest provisioning** (WinRM/SSH into the VM)

Local Nest optional / empty registry on fresh install is complementary ([#266](https://github.com/dustinestes/Hatchery/issues/266), [ADR-0005](0005-controller-only-package-distribution.md)).

## Consequences

**Good**

- One product shell; Nest providers are first-class optional modules
- Capability gaps live in the [provider matrix](../providers.md), not silent assumptions
- Remote Nest work can share transport helpers without rewriting Controller UI

**Neutral / follow-on**

- Full parity across all Nest cells is not day-one; matrix tracks Planned / N/A
- Libvirt-only rules (e.g. world-readable media for `libvirt-qemu`) stay in the libvirt adapter

**Bad / accepted cost**

- Contributors must look up Nest id → factory instead of importing `LibvirtProvider` in routes
- Call sites that still assume a single local libvirt Nest must be migrated when touched

## Alternatives considered

| Alternative | Why not |
|---|---|
| Three OS-specific Hatchery apps | Diverges product and docs; epic #202 rejects this |
| Keep hard-wired libvirt until UTM/Hyper-V exist | Blocks remoting and Nest-optional install; every later feature rewrites the same seam |
| Big-bang rewrite of `LibvirtProvider` before factory | High risk; factory first, then adapters |
| Collapse Nest transport into guest WinRM/SSH | Different planes; conflating them breaks Remote Nest design |
