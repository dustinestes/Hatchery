<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Nest Health</h1>
<br clear="both">

Nest-plane health gather for a Hatchery Nest: reachability gate, then host resources and Nest prerequisites ([#538](https://github.com/dustinestes/Hatchery/issues/538); [ADR-0039](adr/0039-nest-health-gate-and-nest-storage.md)).

<br>

## Contents

- [Contents](#contents)
- [Gate then deepen](#gate-then-deepen)
- [Nest storage vs Nest cache](#nest-storage-vs-nest-cache)
- [UI](#ui)
- [Settings and schedule](#settings-and-schedule)
- [CLI](#cli)

---

<br>

## Gate then deepen

| Stage | What runs |
|---|---|
| **Gate** | Nest reachability (Local co-located; Remote endpoint TCP then Nest transport) |
| **Deeper (gate OK only)** | CPU count, memory, disk volumes, Nest tool prerequisites |

If the gate fails, deeper fields are unavailable (not zero-filled). Reachability Alerts and the Nest reachability snapshot still update from the gate so capability checks stay gated ([#286](https://github.com/dustinestes/Hatchery/issues/286)).

Module: [`lib/nest_health.py`](../../lib/nest_health.py).

<br>

## Nest storage vs Nest cache

| Noun | Owns |
|---|---|
| **`nest_storage`** | Guest VM disk roots on the Nest (`{nest_storage}/{vm_id}/`) - Nest detail tile; primary path in Nest `extra.nest_storage` |
| **`nest_cache`** | Library / media / automation content root ([#215](https://github.com/dustinestes/Hatchery/issues/215)) |
| Clutch **`storage_path`** | Legacy hatch fallback when Nest volumes are unset |

Free-space status on Nest storage rows: Connected / Disconnected / Warn / Error (text + non-color cue). Warn when free space is low; Error when too low to safely hatch (preflight consumption: [#50](https://github.com/dustinestes/Hatchery/issues/50)).

<br>

## UI

On Nest sticky detail:

1. Hero **Health** - ad-hoc Nest Health run; updates the hero reachability badge and status dot, then refreshes status surfaces (footer / bell) without a full page reload
2. **Nest Health** subsection - reachability, CPU, memory, last checked
3. **Storage** tile - register paths (+), Refresh (re-runs Health). Add path uses the shared modal backdrop; pick a Nest **disk** from the latest Health discovery (volume root: Windows drive letter, POSIX mount) plus an optional subdirectory, or enter a full absolute path. Drive letters are Windows-only; the UI uses the universal **disk** noun.
4. **Prerequisites** tile - present / missing Nest tools for the provider (Hyper-V: role/feature, Hyper-V PowerShell module/management tools, and `Get-VM` smoke)

Connections still offers **Test Nest connection** for draft / unsaved Nest rows.

<br>

## Settings and schedule

**Settings → General → Validators → Nest Health**: enable and interval (default 60s). The older **Nest reachability** validator delegates to Nest Health and is off by default.

<br>

## CLI

```bash
uv run hatchery nest health <nest-id>
uv run hatchery --json nest health <nest-id>
```

Also: `hatchery nest test <nest-id>` (connection / capability message for operators and drafts).

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
