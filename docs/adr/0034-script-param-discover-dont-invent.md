# ADR-0034: Script parameters - discover, don't invent

- **Status:** Accepted
- **Date:** 2026-10-11
- **Issues:** [#571](https://github.com/dustinestes/Hatchery/issues/571); absorbs [#148](https://github.com/dustinestes/Hatchery/issues/148); builds on [#113](https://github.com/dustinestes/Hatchery/issues/113)

## Context

Clutch Build/Edit introspects PowerShell `param()` blocks (#113) but treated every value as a quoted string at invoke time and offered only text fields. Typed params such as `[bool]$IncludeManagementTools` failed at guest bind while the hatch step could still look green. Library Scripts already span Windows / Linux / macOS; inventing Hatchery-only constraints or a Windows-only form path would fork the product.

## Decision

1. **Discover, then ensure. Do not invent.** Controllers read scripts via kind adapters and map only declared constraints into a neutral `ParamSpec` (`lib/script_params.py`). Clutch UI widgets and early validation enforce those specs only. Empty metadata means no typed fields and no strict param gate (honest degrade), not guessed types or enums.
2. **One Clutch parameters surface for all script kinds.** Guest OS / file kind selects the reader and encode path; the form does not hard-wire PowerShell widgets.
3. **Adapters are pluggable.** v1 lands a PowerShell (`.ps1`) reader via Controller `pwsh`. Shell (`.sh` / `.bash`) and other kinds register later; until a reader exists they return no specs.
4. **Fail early when metadata exists.** Shared validate runs on Clutch Build/Edit save and hatch preflight (UI + CLI). Guest param-binding failure is a backstop that must not report success.
5. **Typed YAML natives preferred.** Form save emits JSON/YAML bools and numbers when specs say so; load coerces legacy stringly tokens when validating against specs.

## Consequences

- Lab-class failures (string `'True'` into `[bool]`) are blocked before hatch when `pwsh` can introspect the script.
- Linux/macOS script param UX reuses the same pipeline once adapters land; no second Clutch parameters IA.
- Controllers without `pwsh` keep the weaker path (manual YAML params, no strict gate) until introspection is available.
- Hatchery does not become a general static analyzer for every scripting language; each adapter only surfaces what that host can discover reliably.
- PowerShell **parameter sets** (`ParameterSetName`) were considered and are **explicitly unsupported** for now: introspection flattens all params; a future set selector in the Clutch form is deferred until Library scripts need it ([script-parameters.md](../script-parameters.md#powershell-parameter-sets)).

## Alternatives

| Option | Why not |
|---|---|
| Keep string-only params forever | Breaks typed PowerShell; poor UX; late failures |
| Hatchery-declared frontmatter for all scripts | Invents a second SoR beside the script; easy to drift from real `param()` |
| Windows-only form path | Fights multi-guest Scripts layout already in Hatchery-Library |

## Related docs

- Operator reference: [`docs/script-parameters.md`](../script-parameters.md)
- Scripts how-to: [`docs/automations.md`](../automations.md)
- Code: [`lib/script_params.py`](../../lib/script_params.py)
