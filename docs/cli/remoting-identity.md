<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: remoting-identity</h1>
<br clear="both">

Code: [`lib/cli/remoting_identity.py`](../../lib/cli/remoting_identity.py). Lib: [`lib/remoting_identities.py`](../../lib/remoting_identities.py). Parent: [CLI index](README.md). Issue: [#522](https://github.com/dustinestes/Hatchery/issues/522). ADR: [ADR-0030](../adr/0030-controller-remoting-identities.md).

<br>

## Purpose

Manage the Controller **remoting identities** catalog (Hatchery-managed + operator path keys). Nest rows bind via `remoting_identity_id` ([#523](https://github.com/dustinestes/Hatchery/issues/523)); guests authorize via Clutch `remoting.ssh.authorize` ([#524](https://github.com/dustinestes/Hatchery/issues/524)). This command manages the catalog only - it does not write Nest or Clutch bindings.

Private key **bytes** are never stored in SQLite - only path references.

<br>

## Usage

```bash
uv run hatchery remoting-identity [--data-dir PATH] list
uv run hatchery remoting-identity [--data-dir PATH] show <id>
uv run hatchery remoting-identity [--data-dir PATH] generate
uv run hatchery remoting-identity [--data-dir PATH] rotate
uv run hatchery remoting-identity [--data-dir PATH] add-path --id ID --identity-file PATH [--name TEXT] [--cert-path PATH] [--expires-at ISO8601]
uv run hatchery remoting-identity [--data-dir PATH] remove <id> [--delete-files]
uv run hatchery remoting-identity [--data-dir PATH] check [id]
uv run hatchery --json remoting-identity list
```

| Command | Mutates | Notes |
|---|---|---|
| `list` / `show` / `check` | No | Inspect requires an existing data dir |
| `generate` | Yes | Creates Hatchery-managed ed25519 under `data_dir/remoting/` if missing |
| `rotate` | Yes | Replaces Hatchery-managed keypair |
| `add-path` | Yes | Registers an existing Controller private key path |
| `remove` | Yes | Path ids remove freely; Hatchery-managed requires `--delete-files` |

<br>

## Examples

```bash
uv run hatchery remoting-identity generate
uv run hatchery remoting-identity add-path --id lab --identity-file ~/.ssh/lab_ed25519
uv run hatchery --json remoting-identity check
```

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
