<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: vm</h1>
<br clear="both">

**Planned.** Code will live at `lib/cli/vm.py`. Parent: [CLI index](README.md). Issue: [#23](https://github.com/dustinestes/Hatchery/issues/23). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md).

<br>

## Purpose

Nest-scoped VM inventory and lifecycle (Start, Stop, Cull, Snapshot, Revert, health check).

<br>

## Intended surface

```bash
hatchery vm list --nest <id>
hatchery vm start|stop|cull --nest <id> <vm-name>
hatchery vm snapshot|revert --nest <id> <vm-name> --label <name>
hatchery vm health --nest <id> <vm-name>
```

In-process Nest factory / transport. Nest targeting per ADR-0013. Not implemented until #23.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
