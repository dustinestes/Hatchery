# ADR-0031: Sticky submenu shell and Nests Connections IA

- **Status:** Accepted
- **Date:** 2026-10-04
- **Issues:** [#525](https://github.com/dustinestes/Hatchery/issues/525) (shell), [#526](https://github.com/dustinestes/Hatchery/issues/526)–[#529](https://github.com/dustinestes/Hatchery/issues/529) (consumers)
- **Related:** [ADR-0016](0016-library-operator-plane.md) (domain Connections leave Settings), [ADR-0003](0003-nest-registry.md), [ADR-0030](0030-controller-remoting-identities.md) (IA deferred here)
- **How-to:** Settings / Nests operator docs under `docs/`

## Context

VMs and Nests used flat sidebar items plus a left-rail inventory split. Nest registry CRUD lived under Settings → Nests. Operators need dismissible sticky detail tabs (entity name) under product nav, full-width detail, and Nest registry next to Nest inventory (Library Connections precedent).

## Decision

1. **Reusable sticky submenu** (vanilla JS): open / close / activate under a product nav leaf; label truncation with `title` / `aria-label`; scroll overflow; soft cap 12 (dismiss oldest); persist in `sessionStorage`.

2. **Nav groups**

| Nav | Static leaves | Stickies under |
|---|---|---|
| VMs | Inventory | Inventory (VM name) |
| Nests | Inventory, Connections | Connections (Nest name) |

3. **Nest registry** moves from Settings → Nests to **Nests → Connections**. `/settings/nests` redirects. Product graph remains the `nests` table ([ADR-0022](0022-dual-surface-operator-discipline.md)).

4. **Full-width detail** when a sticky is active (not squeezed by inventory left rail).

## Consequences

- Settings loses the Nests section (redirect only).
- Follow-on PRs fill Inventory tiles (#526 / #528), Events console (#527), and sticky detail bodies (#528 / #529).
- Same sticky API for Nest and VM; no Nest-only nav pattern.

## Alternatives considered

| Option | Why not |
|---|---|
| Keep Nest registry in Settings | Fights ADR-0016 product-plane shape |
| Unlimited stickies | Sidebar overflow without a cap |
| localStorage stickies | Stale across days; sessionStorage matches hatch monitoring |
