<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: serve</h1>
<br clear="both">

Code: [`lib/cli/serve.py`](../../lib/cli/serve.py). Parent: [CLI index](README.md). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md). Issue: [#22](https://github.com/dustinestes/Hatchery/issues/22).

<br>

## Purpose

Start the Hatchery **Controller** HTTP process (gunicorn, one sync worker).

<br>

## Usage

```bash
uv run hatchery serve [--data-dir PATH] [--host HOST] [--port PORT]
```

| Flag | Default | Notes |
|---|---|---|
| `--data-dir` | Bootstrap / XDG default | **Session-only.** Never written to Settings or bootstrap YAML. Also available as env `HATCHERY_DATA_DIR` for `gunicorn hatchery:app`. |
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `5000` | Bind port |

Precedence for data dir: CLI / env override > bootstrap `config.yaml` > built-in default.

Missing `--data-dir` paths are created (via normal Controller startup `init_data_dir`) when the app loads.

<br>

## Examples

```bash
# Laptop Controller on localhost
uv run hatchery serve --host 127.0.0.1 --port 5000

# Disposable sandbox (does not rewrite Settings)
uv run hatchery serve --data-dir .hatchery-sandbox --host 127.0.0.1 --port 5000

# Same override with gunicorn
HATCHERY_DATA_DIR=.hatchery-sandbox uv run gunicorn hatchery:app --bind 127.0.0.1:5000 --workers 1
```

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
