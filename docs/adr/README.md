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
❌ Duplicating how-to docs - link the doc instead
```

Prefer writing the ADR in the **same PR** that implements the decision (`Accepted`).

Agents: Cursor rule [`adr-discipline.mdc`](../../.cursor/rules/adr-discipline.mdc) - when a plan or discussion **locks** architecture, write an ADR and **supersede** any ADR the new decision replaces (Status + link; do not delete or renumber).

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
| [0002](0002-library-in-pane-browser.md) | In-pane Library browser (Cached \| Library tabs) | Superseded by [0016](0016-library-operator-plane.md) |
| [0003](0003-nest-registry-provider-factory.md) | Nest registry + provider factory (no hard-wired libvirt) | Accepted |
| [0004](0004-status-surfaces-gather-store-poll.md) | Status surfaces - gather → store → poll | Accepted |
| [0005](0005-controller-only-package-distribution.md) | Controller-only install via OS package managers | Accepted |
| [0006](0006-pluggable-validators.md) | Pluggable validators; Alerts ≠ validator runs | Accepted |
| [0007](0007-library-nest-content-planes.md) | Library / Nest content planes + local-first hatch cache | Accepted |
| [0008](0008-alerts-events-audit-separation.md) | Alerts vs Events vs Audit (Notifications umbrella) | Accepted |
| [0009](0009-library-git-checkout-cache.md) | Library git checkout cache on the Controller | Superseded by [0020](0020-library-forge-path-only.md) |
| [0010](0010-library-forge-providers.md) | Library forge connection type + pluggable providers | Accepted |
| [0011](0011-library-consume-only-no-clutch-roundtrip.md) | Library is consume-only - no Clutch↔forge round-trip | Accepted |
| [0012](0012-library-cache-provenance-drift.md) | Library cache provenance + drift sync | Accepted (reachability/sync axes refined by [0018](0018-library-drift-scenario-matrix.md)) |
| [0013](0013-hatchery-cli-launch-and-operator.md) | Hatchery CLI - launch and operator surfaces | Accepted |
| [0014](0014-optional-local-nest.md) | Optional Local Nest and empty Nest registry | Accepted |
| [0015](0015-settings-partial-writes-worker-services.md) | Partial Settings writes + worker-only runtime services | Accepted |
| [0016](0016-library-operator-plane.md) | First-class Library operator plane (Connections admin) | Accepted |
| [0017](0017-library-connections-bindings-tables.md) | Library connections and bindings as first-class tables | Accepted |
| [0018](0018-library-drift-scenario-matrix.md) | Library source reachability + sync state (scenario matrix) | Accepted |
| [0019](0019-library-disable-excise.md) | Library disable / excise (soft vs teardown depth) | Accepted |
| [0020](0020-library-forge-path-only.md) | Library connections without classic git clone | Accepted |
| [0021](0021-controller-embeddable-operator-plane.md) | Controller as embeddable operator plane | Accepted |
| [0022](0022-dual-surface-operator-discipline.md) | Dual-surface operator discipline (UI + CLI) | Accepted |
| [0023](0023-settings-sqlite-revision-reload.md) | Settings SQLite revision reload across processes | Accepted |
| [0024](0024-answer-files-product-model.md) | Answer Files product model (install-time templates) | Accepted |
| [0025](0025-software-product-model.md) | Software product model (post-boot packages) | Accepted |
| [0026](0026-guest-clutch-environment.md) | Guest and Clutch environment variables for hatch jobs | Accepted |
| [0027](0027-clutch-guest-os-family-firmware-tpm.md) | Clutch Guest OS is family + explicit firmware/TPM | Accepted |
| [0028](0028-hatch-session-clutch-snapshot.md) | Hatch session Clutch snapshot (ignore mid-hatch edits) | Accepted |
| [0029](0029-guest-ssh-bootstrap-and-guest-transport.md) | Guest SSH bootstrap and Guest transport plane | Accepted |
| [0030](0030-controller-remoting-identities.md) | Controller remoting identities (Nest + Guest SSH keys) | Accepted |
| [0031](0031-sticky-submenu-and-nests-connections.md) | Sticky submenu shell and Nests Connections IA | Accepted |
| [0032](0032-guest-environment-ensure-job.md) | Guest environment ensure as one hatch job block | Accepted |
| [0033](0033-software-online-command-only.md) | Online / command-only Software packages (guest HTTPS / winget) | Accepted |

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
