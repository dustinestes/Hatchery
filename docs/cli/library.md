<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: library</h1>
<br clear="both">

Code: [`lib/cli/library.py`](../../lib/cli/library.py). Parent: [CLI index](README.md). Issue: [#434](https://github.com/dustinestes/Hatchery/issues/434). ADR: [ADR-0016](../adr/0016-library-operator-plane.md), [ADR-0022](../adr/0022-dual-surface-operator-discipline.md).

<br>

## Purpose

Operator CLI for the Library plane: convenience enable/disable (Settings `library_enabled`) plus connection and binding CRUD on first-class tables.

<br>

## Usage

```bash
uv run hatchery library [--data-dir PATH] enable|disable
uv run hatchery library [--data-dir PATH] connection list|show|add|remove …
uv run hatchery library [--data-dir PATH] binding list|show|add|remove …
uv run hatchery --json library connection list
```

| Command | Notes |
|---|---|
| `enable` / `disable` | Calls `settings_io.set_exportable_setting("library_enabled", …)` - same SoR as `settings set` |
| `connection list\|show` | Read registry (works while Library is disabled) |
| `connection add\|remove` | Requires Library enabled; `add` upserts by `--id` |
| `binding *` | Same pattern; `--domain` filter on list; media bindings take `--target iso\|virtio` |

Deeper disable/excise teardown (clear links/content/registry) remains UI / follow-on ([ADR-0019](../adr/0019-library-disable-excise.md)).

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
