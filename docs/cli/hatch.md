<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: hatch</h1>
<br clear="both">

**Planned.** Code will live at `lib/cli/hatch.py`. Parent: [CLI index](README.md). Issue: [#23](https://github.com/dustinestes/Hatchery/issues/23). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md).

<br>

## Purpose

Hatch a Clutch onto a Nest from the terminal (same orchestration paths as the UI over time).

<br>

## Intended surface

```bash
hatchery hatch --clutch <file> [--nest <id>]
```

Not implemented until #23. Long-running Remote Nest hatch resilience is Nest-plane work ([#345](https://github.com/dustinestes/Hatchery/issues/345)), not this command’s packaging.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
