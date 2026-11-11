# ADR-0043: Controller extension load for Enterprise tier

- **Status:** Accepted
- **Date:** 2026-11-10
- **Issues:** [#619](https://github.com/dustinestes/Hatchery/issues/619); audit [Hatchery-Enterprise #1](https://github.com/dustinestes/Hatchery-Enterprise/issues/1)
- **Related:** [ADR-0042](0042-open-core-public-and-enterprise-tier.md), [ADR-0006](0006-pluggable-validators.md), [north-star](../north-star.md)
- **Code:** [`lib/extensions/`](../../lib/extensions/)
- **How-to:** [extensions.md](../extensions.md), [enterprise/](../enterprise/)

## Context

ADR-0042 locks open-core: public Hatchery stays a useful Local Nest product; paid hierarchy lives in private `hatchery-enterprise`. The commercial package must attach without forking the Controller or requiring the private package in public CI.

## Decision

1. **Try-import load.** `lib.extensions.load_extensions()` imports `hatchery_enterprise` when present and calls `register(api)`. `ImportError` leaves free defaults. No plugin marketplace / entry-point matrix in v1.
2. **No public env master switch.** Free Controller does not document or honor commercial env knobs. Dev free-mode and pack toggles live only in the private Enterprise package (internal docs + workspace gates).
3. **`ExtensionApi`** exposes: `set_entitlements`, `register_cli`, `register_flask`, `register_validator` (validator delegates to ADR-0006 registry).
4. **Free `Entitlements`:** `max_nests=1`, empty `features`. Free edition never reads a commercial license file.
5. **Wire-up:** CLI `build_parser` loads then `apply_cli`; Flask `start_runtime_services` loads then `apply_flask`.
6. **Docs:** operator how-to stays public (`docs/extensions.md`, `docs/enterprise/`). Private Enterprise `docs/internal/` holds commercial ops and **dev-only** toggle docs - not customer-facing README.

## Consequences

**Good**

- Public CI stays MIT-only; Enterprise is optional
- Narrow API mirrors validators; no second framework
- Free product vacuum: no Enterprise env vocabulary in public load path

**Neutral / follow-on**

- Enterprise production entitlements: signed license file / portal ([Hatchery-Enterprise #2](https://github.com/dustinestes/Hatchery-Enterprise/issues/2))
- Maintainer overrides gated in private package (workspace marker now; signed **developer** license class later - still Hatchery Enterprise, not a public SKU)
- Nest Agent and Remote Nest implement behind this API in private code
- Optional entry points if third-party packs appear later

**Bad / accepted cost**

- Process-global API/load flags need test reset helpers
- Enterprise CLI commands must set `defaults(run=…)` for dispatch
- Determined holders of the private package can still read source (ADR-0042 acceptable-loss piracy stance)

## Alternatives considered

| Alternative | Why not |
|---|---|
| Public `lib/enterprise/` with paid implementations | Would publish paid source as MIT |
| Public `HATCHERY_ENTERPRISE=0` master switch | Leaks commercial packaging into free product; free users never need it |
| Mandatory entry-point discovery | Overkill for one commercial package |
| Always-on license DRM in free | Conflicts with ADR-0042 offline / free vacuum story |
