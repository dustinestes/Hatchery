# Architecture Decision Records

Short records of decisions that constrain future Hatchery code.

Product docs under [`.hatchery/docs/`](../) explain **how** things work for operators and contributors. ADRs explain **why** a shape was chosen so the same debate is not reopened into a conflicting design.

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

### Backfill candidates (not written yet)

Write these only when the decision is revisited or someone asks “why”:

- Nest registry / factory (#206 / #207)
- Status surfaces gather → store → poll (#282)
- Controller-only package-manager distribution (#273)

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
