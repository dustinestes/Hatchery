# ADR-0032: Guest environment ensure as one hatch job block

- **Status:** Accepted
- **Date:** 2026-10-04
- **Issues:** [#554](https://github.com/dustinestes/Hatchery/issues/554), [#557](https://github.com/dustinestes/Hatchery/issues/557), [#558](https://github.com/dustinestes/Hatchery/issues/558)
- **Related:** [ADR-0025](0025-software-product-model.md), [ADR-0026](0026-guest-clutch-environment.md), [#501](https://github.com/dustinestes/Hatchery/issues/501), [#482](https://github.com/dustinestes/Hatchery/issues/482)

## Context

Reserved `HATCHERY_*` env persist (ADR-0026), guest directory layout (ADR-0025), and the `Write-HatchEvent` helper were landing as related but easy-to-fragment hatch narratives. Operators and contributors need one early hatch job where **all** guest environment requirements live, with start/end hatchery-context events, so new requirements do not invent parallel paths.

Injecting helper function bodies into every user script is fragile (PowerShell `param()` ordering, DRY drift, user scripts looking “owned” by Hatchery). Guest builtins should be localized once and consumed by later jobs via normal PowerShell discovery.

Linux and macOS remoting payloads are not ready for full ensure. Staging those platforms as separate issues must still reuse the same Controller hook.

## Decision

1. **One Controller hook:** `ensure_guest_environment` (and `ensure_plan_summary` for events) runs after remoting is ready and **before** user Script/Software automations. Hatch lifecycle always calls this hook; it does not open a second ensure path per platform.

2. **Catalog (v1)** - requirements that belong in this job:

   | Requirement | Role |
   |---|---|
   | Reserved `HATCHERY_*` path env (incl. `HATCHERY_MODULES`) | Persist Machine + process env for jobs |
   | `PSModulePath` | Machine **append** of `HATCHERY_MODULES` (WinPS + pwsh) |
   | Clutch `environment` with `persist: true` | Persist (scope/mode per ADR-0026) |
   | Guest Hatchery directory layout | Ensure `root` / `logs` / `temp` / `software` / `modules` |
   | Hatchery PowerShell module | Install `HATCHERY_ROOT\modules\Hatchery\` (`Hatchery.psd1` + `Hatchery.psm1` exporting `Write-HatchEvent`) |

   New guest environment requirements **must** extend this catalog and the ensure payload, not a parallel hatch step.

3. **No helper-body injection into user scripts:** Controllers do not splice `Write-HatchEvent` (or other Hatchery functions) into operator-authored script text. Clutch parameter binding is the only value-binding into the user scriptblock. Process env for reserved / Clutch / job log path is applied in an **outer** scope so `param()` stays first inside the user script. `Write-HatchEvent` is available via module autoload on `PSModulePath` (and a thin process `PSModulePath` append for remoting reliability).

4. **Platform payloads:** Windows lands with #554. Linux (#557) and macOS (#558) register payloads in the same hook when remoting can run them; until then the hook returns a skipped success for that family and events say so.

5. **Events:** Start block, per-catalog `Ensure: …` lines, end (or fail) block under hatchery context. Fail the hatch on ensure failure.

6. **Cleanup:** Library cleanup removes the guest tree (module files), unloads the module, strips the Hatchery entry from Machine `PSModulePath`, and clears reserved Machine env (including `HATCHERY_MODULES`). Linux/macOS stubs point at #557 / #558.

7. **Non-goals:** Changing `[HATCH:LEVEL]` wire format; forcing Linux/macOS remoting in this ADR; requiring users to call `Import-Module` explicitly (autoload is the contract).

## Consequences

- Env persist, dirs, module install, and `PSModulePath` are one ensure job.
- UI reserved-env catalog surfaces `HATCHERY_MODULES` and `PSModulePath` (append).
- Follow-on guest OS work has a fixed insertion point.
- ADR-0026 remains the env name/persist contract; this ADR locks **when** / **where** that contract (plus dirs/module) runs, and that helpers are modules not script rewrites.

## Alternatives considered

- **Thin-inject helper function into every script:** rejected; fragile around `param()`, not DRY, couples Hatchery internals to user script text.
- **Phased sub-issues inside one Windows issue:** rejected; issues stage work across platforms, not internal phases of one ensure job.
- **Separate hatch steps per requirement:** rejected; fragments operator event feed and invites parallel paths for the next requirement.
