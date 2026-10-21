# ADR-0040: Nest-reported nest_cache sync (Controller aggregates)

- **Status:** Accepted
- **Date:** 2026-10-20
- **Issues:** [#608](https://github.com/dustinestes/Hatchery/issues/608), parent [#215](https://github.com/dustinestes/Hatchery/issues/215)
- **Related:** [ADR-0007](0007-library-nest-content-planes.md), [ADR-0006](0006-pluggable-validators.md), [#609](https://github.com/dustinestes/Hatchery/issues/609), [#345](https://github.com/dustinestes/Hatchery/issues/345), [#611](https://github.com/dustinestes/Hatchery/issues/611) (Nest Events)
- **How-to:** [nest-health.md](../nest-health.md) (Cache + Content tiles)

## Context

Remote hatch needs Nest ``nest_cache`` content before attach (ADR-0007). Operators also need a Nest detail view of sync state and nest_cache **content**. If the Controller SHA-walked Remote Nest disks over Nest transport, it would couple SoR to WAN control-plane bandwidth and contradict Nest-owned pull (#609 / #345 instruct/report).

## Decision

1. **Controller aggregates; Nest owns compare.** Persist last Nest report in Settings runtime key ``nest_cache_sync`` (same snapshot shape as Nest Health). Controller never treats SSH/WAN disk SHA of a Remote Nest as SoR.
2. **Local Nest:** Nest plane is this host. Run Nest-side content check **in-process** under Controller ``data_dir`` (``source=local_verify``). List known layout trees without hashing multi-GB ISOs on every check.
3. **Remote Nest:** Explicit Check may record ``unavailable`` until Nest pull (#609). Path Refresh is GET-only. Check must **not wipe** content from a prior Nest-ingested report (``source=nest_report``).
4. **States:** ``unevaluated`` | ``in_sync`` | ``out_of_sync`` | ``syncing`` | ``unavailable``.
5. **Content noun:** File lists use API/UI field **content** (not inventory). Domain/VM inventory stays a separate product noun.
6. **Latest message:** Report includes a single ``message`` for the Cache tile status console. Full Nest-plane transcripts are Nest Events ([#611](https://github.com/dustinestes/Hatchery/issues/611)), not this snapshot.
7. **Surfaces:** Nest detail **Cache** tile (path, sync badge, latest-message console; Check sync + Refresh) and separate **Content** tile (browse-only table from the last report; Events-style filters); ``POST …/cache/sync/check``; ``PUT …/cache/sync`` ingest; CLI ``hatchery nest cache-sync``; optional ``nest_cache_sync`` validator (default off).

## Consequences

**Good**

- Stable contract for Nest agent / HTTPS pull (#609) to fill reports
- Local operators see content today without waiting on Nest agent
- Dual-surface (UI + CLI) matches ADR-0022

**Neutral / follow-on**

- Nest-owned pull and hatch ensure wait (#609)
- Nest Events (#611) for multi-line Controller/Nest status history
- Optional SHA on content items when Nest agent reports them

**Bad / accepted cost**

- Remote Check is a stub until #609 (by design)
- Local content listing is presence listing, not Library tip drift
- Latest ``message`` is not a full transcript until #611

## Alternatives considered

| Alternative | Why not |
|---|---|
| Controller SSH-SHA Remote ``nest_cache`` | Wrong SoR; multi-GB control plane; fights #609 |
| Wait for full Nest job agent before any tile | Blocks Local UX and API contract |
| Reuse ``library_cache_provenance`` rows as Nest content | Wrong plane (operator cache vs Nest cache) |
| Sync-only event log | Rejected - Nest Events (#611) covers Nest plane generally |
| Call nest_cache files “inventory” | Collides with domain/VM inventory product noun |
