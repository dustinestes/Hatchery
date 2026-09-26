# ADR-0021: Controller as embeddable operator plane

- **Status:** Accepted
- **Date:** 2026-09-26
- **Issues:** [#413](https://github.com/dustinestes/Hatchery/issues/413)
- **Related:** [ADR-0003](0003-nest-registry-provider-factory.md) (Nest id → factory), [ADR-0013](0013-hatchery-cli-launch-and-operator.md) (CLI launch + operator), [architecture-nests.md](../architecture-nests.md), epic [#336](https://github.com/dustinestes/Hatchery/issues/336) (CLI), epic [#202](https://github.com/dustinestes/Hatchery/issues/202) (Nest plane), Nest transport helpers [#209](https://github.com/dustinestes/Hatchery/issues/209), remote hatch [#215](https://github.com/dustinestes/Hatchery/issues/215), Nest job agent [#345](https://github.com/dustinestes/Hatchery/issues/345)
- **How-to:** [docs/cli/](../cli/README.md); Nest transport: [nest-transport.md](../nest-transport.md)

## Context

Hatchery already separates **Controller** and **Nest** planes and routes Nest work through a registry and provider factory. The UI and operator CLI are growing on that shape. Without an explicit product north star, it is easy to treat Hatchery as a **standalone adjacent console**: useful next to CI and developer tooling, but not something those systems can *incorporate*.

External developers and operators (human, scripted, or agent-assisted) need:

1. Clear **planes** for management and Nest communication
2. A **stable, documented operator surface** they can call from CI/CD and local tooling
3. Extensibility that does not require forking Hatchery or hard-wiring one hypervisor

That goal is **general product direction**, not a single employer’s harness. Employer and community consumers succeed the same way: Hatchery as an intermediate control plane, not an isolated island.

## Decision

### Product stance

Hatchery’s Controller is an **embeddable operator plane**. CI, developer tools, and automation should be able to inspect and manage Nests and guests through Hatchery’s articulated surfaces. The UI remains first-class for humans; it is **not** the only supported integration path.

### Layers (build toward)

```
External tooling / CI / agents
        │
        ▼
 Controller operator surface
   CLI now (ADR-0013); versioned HTTP operator API later
        │
        ▼
 Shared Nest orchestration (library)
   Nest id → factory; hatch / lifecycle / health
        │
        ▼
 Nest transport client  ≠  guest provision
        │
        ▼
 Nest providers (libvirt / UTM / Hyper-V × Local | Remote)
```

All management paths (UI, CLI, future HTTP) **must** go through shared orchestration and Nest id → factory ([ADR-0003](0003-nest-registry-provider-factory.md)). Do not add hypervisor- or SSH-special cases in route handlers or CI helpers that bypass that seam.

### Operator contract (direction)

| Surface | Role now | Role later |
|---|---|---|
| **Operator CLI** | Primary embeddable surface (`hatchery nest|clutch|vm|hatch…`); in-process; Nest-scoped | Grow mutate (#353), machine-readable output, stable exit codes |
| **UI / Flask routes** | Human Controller shell | Stay; **not** the frozen external API contract |
| **HTTP operator API** | Not shipped | Optional Controller-facing API for remote clients that should not share a data-dir filesystem; same orchestration lib as CLI |

ADR-0013’s rejection of **HTTP-only** operator remains: CLI must work without a running Controller HTTP process. That does **not** forbid a later HTTP operator API *in addition* to CLI.

### Nest communication

- **Nest transport** (SSH default, WinRM where needed) is the Controller’s channel to the Nest *machine* ([nest-transport.md](../nest-transport.md))
- **Guest provision** stays separate (`lib/provision.py` and guest paths)
- Long-running remote hatch resilience (job payload, reconnect, event catch-up) stays Nest-plane ([#345](https://github.com/dustinestes/Hatchery/issues/345)), shared by UI and CLI once designed
- Remoting helpers ([#209](https://github.com/dustinestes/Hatchery/issues/209)) and remote hatch ([#215](https://github.com/dustinestes/Hatchery/issues/215)) harden this plane; they do not invent a second control model

### Documentation and discoverability

Operator nouns stay product terms (Controller, Nest, Clutch, Hatch). CLI lifecycle verbs prefer universal language (`destroy`, `snap take|list|apply|delete`, `health`) per [ADR-0013](0013-hatchery-cli-launch-and-operator.md). Docs and CLI help should be enough for an operator or agent to **infer how to use** Hatchery without reading Flask handlers. Prefer:

- Documented commands and Nest targeting (`--nest`, empty-registry guidance)
- Predictable, machine-friendly inspect/mutate output over time (JSON where it helps automation)
- ADRs + `docs/cli` / architecture pages over undocumented `/api/...` shapes

### Non-goals

- One company’s CI topology or proprietary agent protocol as the product API
- Treating today’s UI JSON routes as a versioned public contract
- Replacing Nest providers with a generic “run any SSH script” product
- Requiring a always-on Controller daemon for every local operator action

## Consequences

**Good**

- Clear north star for CLI, Nest transport, and future HTTP work
- Hatchery can sit **inside** automation stacks instead of only beside them
- Agents and humans share the same nouns and orchestration path
- Aligns with Controller-only distribution ([ADR-0005](0005-controller-only-package-distribution.md)) and optional Local Nest ([ADR-0014](0014-optional-local-nest.md))

**Neutral / follow-on**

- Operator mutate CLI ([#353](https://github.com/dustinestes/Hatchery/issues/353))
- Nest transport helpers ([#209](https://github.com/dustinestes/Hatchery/issues/209)), remote hatch ([#215](https://github.com/dustinestes/Hatchery/issues/215)), Nest job agent ([#345](https://github.com/dustinestes/Hatchery/issues/345))
- Explicit machine-readable CLI output and a later HTTP operator API ADR when implementation starts
- Keep UI routes free to evolve until a dedicated operator API is cut

**Bad / accepted cost**

- Shared orchestration must stay tidy so UI and CLI do not diverge
- “Embeddable” raises the bar on docs, stability, and Nest remoting before every consumer scenario works

## Alternatives considered

| Alternative | Why not |
|---|---|
| UI-only product; CLI is debug-only | Fights CI/CD and agent incorporation; leaves Nest factory underused |
| Freeze Flask `/api/...` as the public API | Couples consumers to UI shapes; conflicts with in-process CLI (ADR-0013) |
| HTTP-only remote control plane | Blocks offline/local Nest inspect; rejected as sole path in ADR-0013 |
| Employer-specific adapter as core | Narrows the product; community and other orgs lose a clean plane |
| Bypass Nest factory for “simple” SSH from CI | Second control path; breaks multiplatform Nest story |
