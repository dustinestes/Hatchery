<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: vm</h1>
<br clear="both">

Code: [`lib/cli/vm.py`](../../lib/cli/vm.py). Parent: [CLI index](README.md). Issue: [#23](https://github.com/dustinestes/Hatchery/issues/23) (inspect slice). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md).

<br>

## Purpose

Nest-scoped VM inventory. Lifecycle (Start, Stop, Cull, Snapshot, Revert, health) is deferred to a follow-on under [#23](https://github.com/dustinestes/Hatchery/issues/23).

<br>

## Usage (shipped)

```bash
uv run hatchery vm [--data-dir PATH] list [--nest <id>]
```

| Flag | Notes |
|---|---|
| `--nest` | Required unless exactly one Nest is registered (ADR-0014) |
| `--data-dir` | Session-only Controller data dir (must already exist for inspect) |

`list` asks the Nest hypervisor via the provider factory (local libvirt → `virsh`). Remote Nest VM ops are not available yet (clear error). Live inventory is not a Controller SQLite table; remote last-known cache is Nest-plane work ([#345](https://github.com/dustinestes/Hatchery/issues/345)). Inspect does not create a missing data directory or database.

<br>

## Planned (not in this slice)

```bash
hatchery vm start|stop|cull --nest <id> <vm-name>
hatchery vm snapshot|revert --nest <id> <vm-name> --label <name>
hatchery vm health --nest <id> <vm-name>
```

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
