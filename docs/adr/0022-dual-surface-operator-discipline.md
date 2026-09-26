# ADR-0022: Dual-surface operator discipline (UI + CLI)

- **Status:** Accepted
- **Date:** 2026-09-26
- **Issues:** [#435](https://github.com/dustinestes/Hatchery/issues/435)
- **Related:** [ADR-0013](0013-hatchery-cli-launch-and-operator.md) (CLI surfaces), [ADR-0021](0021-controller-embeddable-operator-plane.md) (embeddable plane), [ADR-0016](0016-library-operator-plane.md) (Settings owns Library enable only), Settings CLI [#344](https://github.com/dustinestes/Hatchery/issues/344), Library CLI [#434](https://github.com/dustinestes/Hatchery/issues/434), epic [#336](https://github.com/dustinestes/Hatchery/issues/336)
- **How-to:** [docs/cli/](../cli/README.md); agents: [`.cursor/rules/operator-plane.mdc`](../../.cursor/rules/operator-plane.mdc)

## Context

The Controller UI and operator CLI are both first-class, but it is easy to ship a capability only in Flask routes or only in a pane and leave automation behind. [ADR-0021](0021-controller-embeddable-operator-plane.md) already requires shared orchestration; it does not spell out **when** a feature must grow a CLI noun, or how **Settings flags** relate to **product** CLIs (Library, Nest, …).

Without that split, teams either:

1. Stuff first-class tables into `settings get|set`, or
2. Build UI-only admin for connections/bindings and force operators to use the browser for CI-shaped work

## Decision

### 1. Two stores, two CLI families

| Kind of state | Persistence | CLI |
|---|---|---|
| Exportable Controller flags / maps | SQLite `app_settings` (and bootstrap only for `data_dir`) | `hatchery settings …` ([#344](https://github.com/dustinestes/Hatchery/issues/344)) |
| First-class product graphs (Library connections/bindings, Nest registry, …) | Dedicated tables / libs | Product nouns (`hatchery library …`, `hatchery nest …`, …) |

Do **not** serialize Library connections or Nest rows as ad-hoc Settings keys.

### 2. Convenience verbs for product enable flags

When Settings owns a feature toggle (example: `library_enabled`), the product CLI **may** expose short verbs such as `hatchery library enable|disable`. Those verbs **must** call the **same** Settings write helper as `settings set` (shared lib in-process). They are UX sugar, not a second source of truth. Deeper teardown (clear links / content / registry) stays on the product command and follows existing ADRs (e.g. [ADR-0019](0019-library-disable-excise.md)).

### 3. Dual-surface by default

When adding or extending an **operator** capability (anything CI or an external tool should eventually call):

1. Implement shared logic in `lib/` (or Nest factory paths) once
2. Expose UI **and** plan CLI in the same epic or with an explicit follow-on issue opened in that PR
3. Document the CLI under `docs/cli/`; do not treat Flask `/api/...` as the public contract

Explicit deferral is allowed (“CLI in #N”) but silent UI-only growth for operator features is not.

### 4. Non-goals for this ADR

- Requiring CLI parity for pure presentation / a11y chrome with no operator contract
- Freezing a versioned HTTP operator API (still future under ADR-0021)
- Landing Settings or Library CLI implementations (tracked issues above)

## Consequences

- Agents and humans have a clear checklist: Settings key vs product CLI vs convenience enable verb
- Less drift between UI and embeddable surfaces
- Library CLI (#434) and Settings CLI (#344) stay correctly separated while sharing the enable-flag write path
- More issues up front when a pane grows mutate power without a CLI plan

## Alternatives

| Option | Why not |
|---|---|
| Everything under `hatchery settings` | Collides with first-class tables; fights ADR-0016 / ADR-0017 |
| UI-only until “later” with no issue | Reproduces embeddable-plane drift; conflicts with ADR-0021 |
| CLI shells out to `hatchery settings` as a subprocess | Fragile; prefer in-process shared lib |
