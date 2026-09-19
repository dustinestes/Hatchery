# ADR-0007: Library / Nest content planes + local-first hatch cache

- **Status:** Accepted
- **Date:** 2026-09-19
- **Issues:** [#198](https://github.com/dustinestes/Hatchery/issues/198) (epic), related [#215](https://github.com/dustinestes/Hatchery/issues/215)
- **How-to:** [library.md](../library.md)

## Context

Media, scripts, and Clutches must reach a Nest before hatch attach. Remote Nests cannot treat the operator laptop’s data directory as attachable paths. A CMS-style catalog GUID, live remote ISO URLs in Clutches, or attach-over-WAN without a Nest cache would couple Library to Nest transport in fragile ways.

We needed a content architecture that:

1. Separates Library **sources**, operator **cache**, Nest **cache**, and hypervisor **attach**
2. Identifies bytes portably across machines
3. Makes hatch fail closed when Nest cache is incomplete (unless a future opt-in says otherwise)

## Decision

1. **Planes:** Library sources → operator cache (`data_dir`) → Nest cache → hypervisor attach/run
2. For a **local Nest**, operator data dir **is** the Nest cache
3. For a **remote Nest**, ensure/sync fills Nest cache before hatch; do not stream multi-GB ISOs over the control plane at attach time (v1)
4. **Identity:** basename + **SHA-256** (no GUID catalog)
5. **Settings owns** source config; domain panes keep in-context Import (file always; library browse when enabled — see [ADR-0002](0002-library-in-pane-browser.md))
6. Default hatch contract: **validate Nest cache** has required content before provider create/attach

Explicit non-goals (v1): CMS, live remote ISO URLs in Clutches, allow-remote-content attach, continuous settings git watch.

API provider plug-ins for Library catalogs are a separate decision ([ADR-0001](0001-library-api-adapters.md)).

## Consequences

**Good**

- Remote hatch has a clear ensure/preflight story (#215)
- Clutch references stay basename-friendly; checksums catch wrong bytes
- Library can grow connection types without changing attach semantics

**Neutral / follow-on**

- Future **allow remote content** opt-in for high-bandwidth / all-local DC networks
- Shared storage the Nest already mounts counts as Nest cache when paths resolve there

**Bad / accepted cost**

- Hatch fails closed until Nest cache is ready (by design)
- Contributors must not pass operator-only paths to Remote Nest attach

## Alternatives considered

| Alternative | Why not |
|---|---|
| GUID catalog / CMS | Overbuilt; Clutches already use basenames |
| Live remote ISO URLs in Clutches | Fragile at attach; couples Catalog to hypervisor |
| Allow-remote-content as default | Wrong default for laptops and WAN; opt-in later |
| Attach from operator cache over Nest transport | Multi-GB control-plane copies; fails closed instead |
