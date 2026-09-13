<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Settings Storage</h1>
<br clear="both">

How Hatchery splits the external bootstrap file from Settings stored in SQLite.

<br>

## Contents

- [Contents](#contents)
- [Why Two Places](#why-two-places)
- [Bootstrap File](#bootstrap-file)
- [Database Settings](#database-settings)
- [Upgrade From Legacy config.yaml](#upgrade-from-legacy-configyaml)
- [Settings UI](#settings-ui)

---

<br>

## Why Two Places

Hatchery must know the **data directory** before it can open `hatchery.db`. That pointer cannot live only inside the database. Everything else that the Settings panes edit can — and should — live next to other app state in SQLite (Nest registry, secrets later, expiry tiers today).

| Concern | Store |
|---|---|
| Where is the data directory / DB? | Bootstrap file (and later CLI `--data-dir`, [#22](https://github.com/dustinestes/Hatchery/issues/22)) |
| Operational Settings | SQLite `app_settings` |

<br>

## Bootstrap File

Default location (XDG):

```
~/.config/hatchery/config.yaml
```

Override the config home with `XDG_CONFIG_HOME`. The file is intentionally minimal:

```yaml
data_dir: /home/you/.local/share/hatchery
```

Default data directory (XDG):

```
~/.local/share/hatchery
```

Override with `XDG_DATA_HOME`. Inside that directory: `hatchery.db`, `clutches/`, `media/`, `automation/`.

<br>

## Database Settings

Table: `app_settings` (`key` TEXT PRIMARY KEY, `value` TEXT JSON).

| Key | Settings section | Notes |
|---|---|---|
| `bg_interval` | General | Background validation seconds (minimum 10) |
| `show_passwords` | Security | VM inventory password visibility |
| `nest_key_alert_tiers` | Security | Nest SSH expiry alert windows |
| `nest_ssh_identities` | Security | Tracked identities (until Nest registry) |
| `display_timezone` | Display | `UTC` or `local` for Events |

Managed by `lib/config.py` after `db.init_db` via `bind_db()` / `save()`.

<br>

## Upgrade From Legacy config.yaml

Older installs stored every setting in `config.yaml`. On first load after upgrade:

1. Hatchery reads any non-`data_dir` keys from the YAML into memory
2. Rewrites the bootstrap file to **only** `data_dir`
3. After `init_db`, `bind_db()` writes those values into `app_settings` if the table is empty

Existing installs keep their Settings without manual edits.

<br>

## Settings UI

- **General** — edits `data_dir` (bootstrap) and `bg_interval` (DB). Changing the data directory re-opens `hatchery.db` under the new path.
- **Security** / **Display** — write only to SQLite; bootstrap is unchanged.

The disabled “Bootstrap file” field on General shows the path to the external YAML pointer.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
