# ADR-0039: Nest Health gate-then-deepen and nest_storage volumes SoR

- **Status:** Accepted
- **Date:** 2026-10-17
- **Issues:** [#538](https://github.com/dustinestes/Hatchery/issues/538)
- **Related:** [ADR-0006](0006-pluggable-validators.md), [ADR-0036](0036-pre-mint-vm-uuid-nest-storage.md), [#215](https://github.com/dustinestes/Hatchery/issues/215) (`nest_cache`), [#286](https://github.com/dustinestes/Hatchery/issues/286)
- **How-to:** [nest-health.md](../nest-health.md)

## Context

Nest sticky detail had only **Test Nest connection** and a reachability snapshot. Guest VM disks already resolve via Nest `extra.nest_storage` → Clutch `storage_path` → provider default (ADR-0036), but operators had no Nest-plane UI to register storage volumes or see host free space / Nest tool gaps. Reachability, capability, and host resources were separate mental models.

## Decision

1. **Nest Health compose:** `lib/nest_health.py` runs a **gate** (`nest_reachability.probe_nest`) then, only if the gate passes, deeper probes: CPU, memory, disk discovery, and Nest prerequisites (`requirements.check_nest`).
2. **Reachability ⊂ Health:** Scheduled gather is the `nest_health` validator. `nest_reachability` remains registered for Settings/history compatibility, defaults to disabled, and delegates to the same Nest Health gather. Gate results continue to update `nest_reachability_status` and Nest reachability Alerts so footer / capability gating (`is_reachable_for_capability`) keep working.
3. **`nest_storage` volumes SoR:** Operator-registered paths live in Nest `extra.nest_storage_volumes` with a primary mirrored to `extra.nest_storage` for the provider factory. Distinct from **`nest_cache`** (content root; #215). Clutch `storage_path` remains a legacy fallback for hatch disk roots until volumes cover the Nest.
4. **Surfaces:** Nest detail Health hero + Nest Health subsection; Nest storage and Nest prerequisites tiles; Settings interval via the Nest Health validator; CLI `hatchery nest health`.
5. **Guest Health align:** `guest_health` returns the same gate / `deeper_ran` shape (no guest host metrics yet; schedule remains #541).

## Consequences

- Ad-hoc Health and the Nest Health validator share one gather path.
- Free-space Warn/Error on volumes is available for hatch preflight (#50) without baking Nest packages into Controller install (#273).
- Operators must register a Nest storage path (or keep Clutch `storage_path` / provider default) for `{nest_storage}/{vm_id}/` layout.

## Alternatives considered

- **Separate Nest Health Settings key outside validators:** Rejected; validators already own Nest-scoped intervals (ADR-0006).
- **SQLite column for nest_storage:** Deferred; `extra` already feeds the factory and avoids a migration for volume lists.
- **Merge Nest and Guest trust / health modules:** Rejected; planes stay separate (ADR-0029).
