<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Database</h1>
<br clear="both">

What Hatchery stores in SQLite, what it doesn't, and why.

<br>

## Contents

- [Contents](#contents)
- [Overview](#overview)
- [Design Boundary](#design-boundary)
- [Location and Lifecycle](#location-and-lifecycle)
- [What Lives in the Database](#what-lives-in-the-database)
- [What Does Not](#what-does-not)

---

<br>

## Overview

Hatchery uses a single SQLite database (`hatchery.db`) for internal state — things the application generates and tracks at runtime. It requires no configuration, no installation step, and no database skills. The file is created automatically on first startup.

The database uses Python's built-in `sqlite3` module. No additional dependencies.

<br>

---

## Design Boundary

**The database is for app-generated internal state only. User-authored data stays as flat files.**

This boundary is intentional and permanent. The reasons:

**Version control works on flat files.**
Clutch definitions, automation scripts, and configuration are things users author, review, and share. Storing them in SQLite means a `git diff` tells you nothing, a code review can't inspect them, and a team on GitHub or GitLab can't track changes over time. As YAML or plain text, they're first-class version-controlled artifacts.

**No database skills required.**
Users shouldn't need to know SQL to move, back up, inspect, or modify their Hatchery data. A file in `~/.local/share/hatchery/clutches/` can be opened in any text editor, copied with `cp`, diffed with `diff`, and read by any script in any language. A SQLite row cannot.

**External tooling integrates cleanly.**
Scripts, extensions, and third-party tools that want to consume Hatchery data can read flat files directly. No database driver, no export step, no schema knowledge required.

**Recovery is straightforward.**
If the database is lost or corrupted, Hatchery recreates it on next startup. No user data is lost. If a config file is lost, the user knows exactly what they're missing and can restore it from version control.

<br>

---

## Location and Lifecycle

```
~/.local/share/hatchery/hatchery.db
```

The database lives at the root of the data directory alongside `clutches/`, `media/`, and `automation/`. If the data directory is relocated in Settings, the database moves with it. The `automation/` directory is further divided into `os_config/` (answer files, cloud-init) and `scripts/` (post-boot scripts).

**First run:** Created automatically. Schema is initialized with `CREATE TABLE IF NOT EXISTS` — safe to call on every startup.

**Upgrades:** Existing data is preserved. The idempotent schema creation means upgrading Hatchery never destroys the database.

**Reset:** Delete the file. Hatchery recreates it on next startup. Because user-authored data lives in flat files, a database reset loses only app-generated state (notification history, instance tracking) — not Clutch definitions or configuration.

The file is not included in the Hatchery source repository.

<br>

---

## What Lives in the Database

| Data | Table | Why here |
|---|---|---|
| Environment alerts | `alerts` | App-generated, stateful — tracks active/resolved health conditions; needs filtering and querying |
| Activity history | `activity` | App-generated, timestamped, immutable — audit trail of user actions and provisioning events |
| Clutch instance state | `clutch_instances` | App-observed runtime state, not user-authored — tracks which VMs were hatched from which Clutch |

<br>

---

## What Does Not

| Data | Where it lives | Why |
|---|---|---|
| Clutch definitions | `clutches/*.yaml` | User-authored — version controlled, human-readable, shareable |
| OS config files | `automation/os_config/*` | User-authored — same reasons |
| Post-boot scripts | `automation/scripts/*` | User-authored — same reasons |
| Application configuration | Config file (YAML) | User-authored — editable outside the app, survives DB reset |
| Source images | `media/*` | Binary files — not relational data |
| Frozen VM states (snapshots) | Managed by libvirt/virsh | Owned by the hypervisor, not Hatchery |

For the full schema reference — table definitions, columns, and maintenance details — see [`schema/database.md`](schema/database.md).

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Where environments hatch</div>
<br clear="both">
