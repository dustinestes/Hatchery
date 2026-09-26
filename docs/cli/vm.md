<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: vm</h1>
<br clear="both">

Code: [`lib/cli/vm.py`](../../lib/cli/vm.py). Parent: [CLI index](README.md). Issue: [#353](https://github.com/dustinestes/Hatchery/issues/353). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md).

<br>

## Purpose

Nest-scoped VM inventory and lifecycle. Power, destroy, snap, and guest health run in-process via the Nest provider factory (no Controller HTTP required).

<br>

## Usage

```bash
uv run hatchery vm [--data-dir PATH] list [--nest <id>]
uv run hatchery vm [--data-dir PATH] start|stop|force-stop|destroy [--nest <id>] <vm-name>
uv run hatchery vm [--data-dir PATH] health [--nest <id>] <vm-name>
uv run hatchery vm [--data-dir PATH] snap take [--nest <id>] <vm-name> --label <id>
uv run hatchery vm [--data-dir PATH] snap list [--nest <id>] <vm-name>
uv run hatchery vm [--data-dir PATH] snap apply [--nest <id>] <vm-name> <label>
uv run hatchery vm [--data-dir PATH] snap delete [--nest <id>] <vm-name> <label>
```

| Flag / verb | Notes |
|---|---|
| `--nest` | Required unless exactly one Nest is registered (ADR-0014) |
| `--data-dir` | Session-only Controller data dir (must already exist for these commands) |
| `destroy` | Remove VM and storage (`destroy_vm`); CLI uses plain destroy, not Cull |
| `snap *` | VM state snapshot (Hyper-V calls this a checkpoint) |
| `health` | Guest IP + WinRM TCP reachability (exit 1 if unreachable) |

Remote Nest VM ops are not available yet (clear error). Live inventory is not a Controller SQLite table.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
