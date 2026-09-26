# ADR-0011: Library is consume-only - no Clutch↔forge round-trip

- **Status:** Accepted
- **Date:** 2026-09-19
- **Issues:** [#316](https://github.com/dustinestes/Hatchery/issues/316)
- **How-to:** [library.md](../library.md)
- **Related:** [ADR-0007](0007-library-nest-content-planes.md) (planes + basename/SHA-256), [ADR-0010](0010-library-forge-providers.md) (forge consume path), [#308](https://github.com/dustinestes/Hatchery/issues/308) (pull provenance - attribution only, not authoring)

## Context

Library connections (path, HTTPS, git clone, API catalogs, forge providers) let Hatchery **list and pull** into the operator domain cache. Clutch YAML is Hatchery-specific: media basenames, automation script names, reboot flags, parameters.

We considered features that would blur “consumer” into “author”:

1. **Import Clutch from Library** - resolve YAML refs to catalog hits by name (and later by provenance)
2. **Export Cached Clutch/script to a binding** - write or re-associate files toward a connection
3. **Push back to a forge** - commit / PR / merge on GitHub (and later GitLab, Bitbucket, Gitea)

Forces against building that now:

- Write semantics differ wildly by connection type; git/forge write-back is an SCM product (branches, reviews, conflicts, token scopes)
- Hatchery’s north star is orchestration over **operator-owned** sources - not becoming the catalog source of truth
- Name-only mapping is fragile; durable links belong with [#308](https://github.com/dustinestes/Hatchery/issues/308) provenance for **sync/orphan UX**, not for publishing

## Decision

1. Library remains **consume-only**: test / list / pull (create-only into operator cache). No forge or git **push**, no “export to binding” authoring flow, no Clutch round-trip that invents remote paths from local YAML.
2. Operators author and version Clutches/scripts in their own repos or shares; Hatchery pulls and runs from the operator cache (planes in [ADR-0007](0007-library-nest-content-planes.md)).
3. [#308](https://github.com/dustinestes/Hatchery/issues/308) may store **pull provenance** (who we pulled from) - that does **not** authorize write-back or auto-publish.
4. Demo seeding uses a separate sample catalog repo ([#315](https://github.com/dustinestes/Hatchery/issues/315) [Hatchery Library](https://github.com/dustinestes/Hatchery-Library)) that operators **add as a Forge connection** - still consume-only. Fresh Controllers with an empty Library registry seed that connection and bindings on first run (`ensure_hatchery_library`); existing registries are never overwritten.

## Consequences

**Good**

- Clear product boundary; forge adapters stay read-oriented (HTTP list/download)
- Avoids multi-provider SCM complexity disproportionate to Hatchery’s role
- Decision is recorded so the idea is not rediscovered as an accidental scope creep

**Neutral / follow-on**

- Name-based Clutch refs continue to assume files already in the operator/Nest cache
- If a future workflow proves consume-only insufficient, a **new ADR** must supersede this one before write-back ships

**Bad / accepted cost**

- No one-click “publish this Clutch to my GitHub binding”
- Operators handle repo layout and CI themselves (acceptable for a consumer)

## Alternatives considered

| Option | Why not (now) |
|---|---|
| Name-map import only (no push) | Still couples Clutch edit UX to every Library type; low value vs pull + local edit |
| Forge push for GitHub only | Still commits/PRs/auth; expands surface before Nest/Controller distribution goals |
| Defer silently (no ADR) | Same debate returns every forge/provider PR |
