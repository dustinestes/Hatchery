# ADR-0028: Hatch session Clutch snapshot (ignore mid-hatch edits)

- **Status:** Accepted
- **Date:** 2026-10-03
- **Issues:** [#514](https://github.com/dustinestes/Hatchery/issues/514)
- **Related:** [ADR-0026](0026-guest-clutch-environment.md), [#19](https://github.com/dustinestes/Hatchery/issues/19) (longer-term Clutch Instance / drift)

## Context

A hatch session already copies automations into `hatch_vm_scripts` at start, but other Clutch-sourced fields (guest `environment`, firmware/TPM create policy, and any path that re-loaded `data_dir/clutches/<file>`) were read from the **live** YAML during provision and Nest details.

Editing a Clutch mid-hatch (Build/Edit) is a legitimate operator action for the **next** hatch. Re-reading the live file made those edits apply to the in-flight session and could break or silently change persist/inject.

## Decision

1. At hatch start (`create_and_start_hatch` → `create_session`), store an immutable JSON snapshot of the resolved Clutch on `hatch_sessions.clutch_snapshot`.
2. Mid-hatch reads prefer that snapshot: `_clutch_vm_for_session`, Nest inventory env/firmware/TPM, retries. Legacy sessions without a snapshot still fall back to the live file.
3. The live Clutch YAML remains the SoR for Build/Edit and the **next** hatch only.
4. Non-goals for this ADR: full Clutch Instance provenance (#19), UI banner when editing a Clutch with an active session, auto-delete of snapshot on archive (column rides with the session row).

## Consequences

- Mid-hatch YAML edits cannot change env persist, job inject, or Nest details for that session.
- Session DB grows by one JSON blob per hatch; size tracks Clutch complexity.
- Operators who intend to “fix” an in-flight hatch by editing the Clutch must Cull / re-hatch (or retry still uses the original snapshot).

## Alternatives considered

- **Per-VM column dumps only:** rejected; a full Clutch snapshot keeps create policy and future Clutch fields consistent without chasing columns.
- **Sidecar file under hatch session dir:** rejected for v1; SQLite column matches other session metadata and simplifies cleanup with the session row.
- **Lock the live file while hatching:** rejected; operators must keep editing for the next hatch.
