<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: serve</h1>
<br clear="both">

Code: [`lib/cli/serve.py`](../../lib/cli/serve.py). Parent: [CLI index](README.md). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md), [ADR-0014](../adr/0014-optional-local-nest.md). Issues: [#22](https://github.com/dustinestes/Hatchery/issues/22), [#266](https://github.com/dustinestes/Hatchery/issues/266).

<br>

## Purpose

Start the Hatchery **Controller** HTTP process (gunicorn, one sync worker).

<br>

## Usage

```bash
uv run hatchery serve [--data-dir PATH] [--nest-local] [--host HOST] [--port PORT]
```

| Flag | Default | Notes |
|---|---|---|
| `--data-dir` | Bootstrap / XDG default | **Session-only.** Never written to Settings or bootstrap YAML. Also available as env `HATCHERY_DATA_DIR` for `gunicorn hatchery:app`. |
| `--nest-local` | off | **Session-only.** Register this Controller as Local Nest id `local` if missing (idempotent). Env: `HATCHERY_NEST_LOCAL=1` / `true` / `yes`. |
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `5000` | Bind port |

Precedence for data dir: CLI / env override > bootstrap `config.yaml` > built-in default.

Missing `--data-dir` paths are created (via normal Controller startup `init_data_dir`) when the app loads. Fresh data dirs start with an **empty** Nest registry unless `--nest-local` (or the env) is set.

“Seed” is reserved for a future fixture/data-load surface, not Nest registration.

<br>

## Examples

```bash
# Laptop Controller on localhost
uv run hatchery serve --host 127.0.0.1 --port 5000

# Disposable Controller-only sandbox (empty Nest registry)
uv run hatchery serve --data-dir .temp/hatchery-sandbox --host 127.0.0.1 --port 5000

# Same sandbox with this Controller registered as Local Nest
uv run hatchery serve --data-dir .temp/hatchery-sandbox-local --nest-local --host 127.0.0.1 --port 5000

# Same overrides with gunicorn
HATCHERY_DATA_DIR=.temp/hatchery-sandbox HATCHERY_NEST_LOCAL=1 \
  uv run gunicorn hatchery:app --bind 127.0.0.1:5000 --workers 1
```

Cursor / VS Code **Run and Debug** configs for production and these sandboxes: [`.vscode/launch.json`](../../.vscode/launch.json) (#337).

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
