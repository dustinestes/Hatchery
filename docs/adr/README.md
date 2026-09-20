# Architecture Decision Records

Short records of decisions that constrain future Hatchery code.

Product docs under [`docs/`](../) explain **how** things work for operators and contributors. ADRs explain **why** a shape was chosen so the same debate is not reopened into a conflicting design.

<br>

## When to write an ADR

```
✅ Extensibility boundaries (“plugin here, not hard-wire there”)
✅ Cross-cutting architecture (planes, install model, status surfaces)
✅ Explicit “we will not do X”

❌ Every bug fix or UI tweak
❌ Duplicating how-to docs — link the doc instead
```

Prefer writing the ADR in the **same PR** that implements the decision (`Accepted`).

Agents: Cursor rule [`adr-discipline.mdc`](../../.cursor/rules/adr-discipline.mdc) — when a plan or discussion **locks** architecture, write an ADR and **supersede** any ADR the new decision replaces (Status + link; do not delete or renumber).

<br>

## Format

Nygard-style, one file per decision:

| Field | Meaning |
|---|---|
| Title | Short decision statement |
| Status | `Proposed` · `Accepted` · `Superseded` (link successor) |
| Date | ISO date |
| Context | Forces and problem |
| Decision | What we chose |
| Consequences | Good, bad, neutral follow-ons |
| Alternatives (optional) | What we rejected and why |

Number files: `NNNN-short-slug.md` (zero-padded). Do not renumber after merge.

<br>

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-library-api-adapters.md) | Library API connection type + pluggable providers | Accepted |
| [0002](0002-library-in-pane-browser.md) | In-pane Library browser (Cached \| Library tabs) | Accepted |
| [0003](0003-nest-registry-provider-factory.md) | Nest registry + provider factory (no hard-wired libvirt) | Accepted |
| [0004](0004-status-surfaces-gather-store-poll.md) | Status surfaces — gather → store → poll | Accepted |
| [0005](0005-controller-only-package-distribution.md) | Controller-only install via OS package managers | Accepted |
| [0006](0006-pluggable-validators.md) | Pluggable validators; Alerts ≠ validator runs | Accepted |
| [0007](0007-library-nest-content-planes.md) | Library / Nest content planes + local-first hatch cache | Accepted |
| [0008](0008-alerts-events-audit-separation.md) | Alerts vs Events vs Audit (Notifications umbrella) | Accepted |
| [0009](0009-library-git-checkout-cache.md) | Library git checkout cache on the Controller | Accepted |
| [0010](0010-library-forge-providers.md) | Library forge connection type + pluggable providers | Accepted |
| [0011](0011-library-consume-only-no-clutch-roundtrip.md) | Library is consume-only — no Clutch↔forge round-trip | Accepted |
| [0012](0012-library-cache-provenance-drift.md) | Library cache provenance + drift sync | Accepted |
| [0013](0013-hatchery-cli-launch-and-operator.md) | Hatchery CLI - launch and operator surfaces | Accepted |

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
