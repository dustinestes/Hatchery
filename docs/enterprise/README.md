# Hatchery Enterprise (docs)

Operator documentation for the **Enterprise** purchase tier of Hatchery. Free / Local Nest how-to stays in the main [`docs/`](../) tree. This section is the left-nav **Enterprise** bucket for a future doc site.

<br>

## Edition

| Edition | What you get |
|---|---|
| **Free (MIT)** | Cross-platform Controller; Local Nest hatch/manage; guest remoting for this Controller’s VMs; thin Library |
| **Enterprise** | Nest Agent, Remote Nest hierarchy, capacity / enroll, content origin, later SSO/RBAC/audit packs |

Brand stays **Hatchery**. Enterprise is a tier, not a second product name. Policy: [ADR-0042](../adr/0042-open-core-public-and-enterprise-tier.md), [north-star](../north-star.md). Load path: [extensions.md](../extensions.md) / [ADR-0043](../adr/0043-controller-extension-load.md).

The commercial package is private (`hatchery-enterprise`). These pages describe capabilities so operators can discover them; they are not a substitute for installing the package + license.

<br>

## How you get it (intent)

| Edition | Deliverables |
|---|---|
| **Free** | Public Hatchery git + free wheel/package when published. Container images are not a first-class supported free channel (you may build your own). |
| **Enterprise** | Same Controller plus commercial wheel (and supported container image) from the license portal, activated by a signed license on the Controller. One general release train for all customers - license packs/limits gate features, not per-customer builds. |

Customers do not receive the private Enterprise git repository. Portal: [hatcheryapp.com](https://hatcheryapp.com) / `license.hatcheryapp.com` (tracked in Hatchery-Enterprise).

<br>

## Coming here as features ship

| Topic | Status |
|---|---|
| Nest Agent | Planned (public [#345](https://github.com/dustinestes/Hatchery/issues/345); implement in Enterprise) |
| Multi-Nest / Remote Nest hierarchy | Planned (Agent-first; Nest SSH removed from free HEAD [#620](https://github.com/dustinestes/Hatchery/issues/620) / [ADR-0044](../adr/0044-free-head-local-nest-only.md)) |
| Content origin / nest_cache pull | Planned ([#609](https://github.com/dustinestes/Hatchery/issues/609) as first Agent job) |
| Entitlements / capacity UI | Planned with package + license portal |

Free docs may link here when a paid counterpart exists (“expanded in Enterprise”).
