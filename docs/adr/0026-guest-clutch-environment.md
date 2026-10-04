# ADR-0026: Guest and Clutch environment variables for hatch jobs

- **Status:** Accepted
- **Date:** 2026-10-03
- **Issues:** [#501](https://github.com/dustinestes/Hatchery/issues/501), epic [#199](https://github.com/dustinestes/Hatchery/issues/199)
- **Related:** [ADR-0025](0025-software-product-model.md) (guest path roles), [ADR-0027](0027-clutch-guest-os-family-firmware-tpm.md), [#502](https://github.com/dustinestes/Hatchery/issues/502) (skip-if-present)

## Context

Guest path roles live in Python (`guest_paths_for(GuestOS)` / ADR-0025). Software authors needed those paths in `software.yaml` / scripts without hard-coding Windows absolute paths or pushing installer-specific rewriting into the Controller runner.

Controller `sys.platform` must never define guest paths. Names must stay identical across guest OS families so one package contract works when Linux/macOS land (#482); only values and shell injection syntax differ.

Operators also need Nest UI visibility of resolved env, process injection for hatch jobs, and optional **persist** on the guest so variables survive after fledged (not only for the job process).

## Decision

1. **Reserved env names** (guest plane, from `guest_paths_for`):

   | Variable | When set | Persist | Role |
   |---|---|---|---|
   | `HATCHERY_ROOT` | Script + Software | Machine (Windows) | Hatchery-managed guest root |
   | `HATCHERY_LOGS` | Script + Software | Machine | Audit / first-boot logs |
   | `HATCHERY_TEMP` | Script + Software | Machine | Ephemeral handoff |
   | `HATCHERY_SOFTWARE` | Script + Software | Machine | Parent of staged Software payloads |
   | `HATCHERY_SOFTWARE_PACKAGE` | Software jobs only | Job-only | `software_package(id)` |
   | `HATCHERY_SOFTWARE_LOG` | Software jobs only | Job-only | `logs/software/{id}.log` |

2. **Clutch field:** per-VM `environment:` as a list of structured entries:

   - `name` / `value`
   - `scope`: `machine` | `user` (Windows; form pivots on `os`)
   - `persist`: bool
   - `mode`: `replace` | `append`

   Flat map shorthand (`KEY: value`) still loads → one entry per key with defaults `scope=machine`, `persist=true`, `mode=replace`. Saves always emit `scope` / `persist` / `mode` explicitly (no default-hiding). User keys must not collide with reserved `HATCHERY_*` names.

3. **Dual surface:**
   - Nest UI shows resolved reserved + Clutch env in a table (columns: name, value, source `reserved`|`clutch`|`software`, scope, persist, mode).
   - Jobs get process injection (reserved + all Clutch user vars) each Script/Software step.
   - Persisted vars are written once on the guest **before automations** (Windows: `[Environment]::SetEnvironmentVariable` + `WM_SETTINGCHANGE`). Hatch events list each name→target. Fail hatch on persist error.

4. **Non-windows:** name/value (+ process inject when remoting exists); persist/scope UI disabled until #482.

5. **Cleanup contract:** Library cleanup scripts wipe the Hatchery guest directory. Windows `hatchery-cleanup-windows.ps1` also clears persisted reserved Machine env (`HATCHERY_ROOT` / `_LOGS` / `_TEMP` / `_SOFTWARE`). Linux/macOS keep env clear as a commented stub until guest persist lands (#482).

6. **Non-goals:** Software `parameters` map; Controller-host env dump into guests; secret/encrypted env store; persisting software-scoped package vars.

## Consequences

- Sample Software packages can reference `$env:HATCHERY_SOFTWARE_LOG` / `$env:HATCHERY_SOFTWARE_PACKAGE` (Windows) without hard-coded `C:\Program Files\Hatchery\…`.
- Guests keep reserved base (and opted-in user) env after fledged when persist is enabled.
- Linux/macOS fill path values in `guest_paths_for` (#482) and switch injection/persist backends when SSH remoting lands; reserved **names** stay stable.

## Alternatives considered

- **Controller command rewriting** (wrap msiexec, rewrite paths): rejected; keeps installer knowledge in packages (ADR-0025 slim runner).
- **Percent-style tokens in yaml rewritten by Controller:** rejected; real process env is clearer for scripts and msiexec `/l*v`.
- **Process injection only (no persist):** rejected; Nest UI showed vars operators expected to remain on the guest.
