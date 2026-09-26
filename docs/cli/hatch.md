<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: hatch</h1>
<br clear="both">

Code: [`lib/cli/hatch.py`](../../lib/cli/hatch.py). Parent: [CLI index](README.md). Issue: [#353](https://github.com/dustinestes/Hatchery/issues/353). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md).

<br>

## Purpose

Hatch a Clutch onto a Nest from the terminal (same orchestration as the UI via [`lib/hatch_lifecycle.py`](../../lib/hatch_lifecycle.py)). Does not require a running Controller HTTP process. By default, waits (polls) until session VMs reach a terminal status.

<br>

## Usage

```bash
uv run hatchery hatch [--data-dir PATH] --clutch <file> [--nest <id>] [--password VM=SECRET]... [--ensure-cache] [--no-wait]
```

| Flag | Notes |
|---|---|
| `--clutch` | Bare filename under `data_dir/clutches/` |
| `--nest` | Required unless exactly one Nest is registered |
| `--password VM=SECRET` | Repeatable; required when the Clutch sets `admin_username` for that VM |
| `--ensure-cache` | Run Nest cache ensure during preflight |
| `--no-wait` | Return after create finishes; do not poll to fledged/failed |
| `--data-dir` | Session-only; may create Controller state (mutate) |

Long-running Remote Nest hatch resilience is Nest-plane work ([#345](https://github.com/dustinestes/Hatchery/issues/345)), not this command’s packaging. Local libvirt is the supported Nest for hatch today.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
