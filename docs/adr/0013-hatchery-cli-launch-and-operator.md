# ADR-0013: Hatchery CLI - launch and operator surfaces

- **Status:** Accepted
- **Date:** 2026-09-20
- **Issues:** [#343](https://github.com/dustinestes/Hatchery/issues/343) (planning), [#22](https://github.com/dustinestes/Hatchery/issues/22), [#23](https://github.com/dustinestes/Hatchery/issues/23), [#344](https://github.com/dustinestes/Hatchery/issues/344) (epic [#336](https://github.com/dustinestes/Hatchery/issues/336))
- **How-to:** [docs/cli/](../cli/README.md); Nest plane: [architecture-nests.md](../architecture-nests.md)

## Context

Hatchery needs a stable **Controller launch** path for sandboxes, services, and eventual package-manager installs ([ADR-0005](0005-controller-only-package-distribution.md)), plus a future **operator** terminal surface for Nest-scoped Clutch/VM work. Early sketches used a separate `hatchery-vm` binary and Local-Nest-only assumptions. Without a locked shape, Phase 1 (`serve`) risks a second packaging story when operator commands arrive.

We also need clear boundaries:

1. Launch flags that point a process at a data dir or bind address must not mutate Settings
2. Operator commands must use Nest id → factory ([ADR-0003](0003-nest-registry-provider-factory.md)), including Remote Nest transport
3. Resilient Remote Nest “push job / async event catch-up” is Nest-plane architecture ([#345](https://github.com/dustinestes/Hatchery/issues/345)), not CLI packaging

## Decision

1. **One** console script `hatchery` (multi-command) via `[project.scripts]`. No second `hatchery-vm` binary.
2. Parser: **stdlib `argparse`** (no new CLI framework dependency for v1).
3. **Launch surface:** `hatchery serve` with session-only `--data-dir`, `--host`, and `--port`. Precedence: CLI flag > bootstrap/config > defaults. Flags **never** write Settings or bootstrap YAML.
4. **Operator surface** (later): subcommands such as `clutch`, `vm`, `hatch`, and `nest` on the same entrypoint, including **list/inspect**. Execution is **in-process**: load registry from `--data-dir`, Nest id → factory / Nest transport. Does not require a running Controller HTTP process.
5. **Nest targeting:** `--nest <id>` when required; if exactly one Nest is registered it may be the default; if zero or many, require `--nest` (or clear empty-registry guidance per [ADR-0014](0014-optional-local-nest.md)).
6. **Phase cut:** [#22](https://github.com/dustinestes/Hatchery/issues/22) ships entrypoint + globals + `serve` only (no stub operator subcommands). [#23](https://github.com/dustinestes/Hatchery/issues/23) adds operator commands. [#344](https://github.com/dustinestes/Hatchery/issues/344) may later add `settings get|set` (persist); that is distinct from launch overrides.
7. Product verbs match the UI (Hatch, Cull, Snapshot, Revert, health / Test Nest). No Brood / Freeze / Thaw / Chirp in user-facing CLI help.
8. Contributor `gunicorn hatchery:app` remains valid when the same runtime overrides apply.

## Consequences

**Good**

- One packaging story toward ADR-0005 (`brew install` → `hatchery serve`)
- Sandboxes and launch.json can pass `--data-dir` without rewriting laptop Settings
- Operator CLI shares Nest factory/transport with the UI (ADR-0003)
- Nest async job agent stays a separate ADR track (#345) without blocking `serve`

**Neutral / follow-on**

- Persisting Settings from the terminal (#344) after Settings stabilize
- Empty Nest registry ([ADR-0014](0014-optional-local-nest.md) / #266) and launch configs (#337)
- Nest hatch job agent + async event catch-up (#345 under epic #202)

**Bad / accepted cost**

- In-process operator CLI duplicates some orchestration entrypoints the UI uses until shared library seams are tidy
- Remote Nest hatch robustness still depends on transport/orchestration work outside this ADR

## Alternatives considered

| Alternative | Why not |
|---|---|
| Second binary (`hatchery-vm`) | Two install/docs surfaces; fights ADR-0005 |
| HTTP-only operator client (require running Controller) | Blocks offline Nest inspect; couples CLI to serve for every power action |
| typer / click for v1 | Extra dependency; argparse is enough for the locked surface |
| Launch flags also write Settings | Breaks sandboxes and “try once” overrides; conflates session with persistence |
| Design Nest async job agent inside this ADR | Wrong plane; would block CLI on a large Nest-agent design ([#345](https://github.com/dustinestes/Hatchery/issues/345)) |
