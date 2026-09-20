<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: settings</h1>
<br clear="both">

**Planned.** Code will live at `lib/cli/settings.py`. Parent: [CLI index](README.md). Issue: [#344](https://github.com/dustinestes/Hatchery/issues/344). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md).

<br>

## Purpose

Read and **persist** Hatchery Settings from the terminal. Distinct from session-only launch overrides on [`serve`](serve.md).

<br>

## Intended surface

```bash
hatchery settings get [key...]
hatchery settings set <key> <value>
```

Honor `--data-dir` for which Controller data root is targeted. Do not overload `hatchery serve --flag` into Settings writes. Not implemented until #344.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
