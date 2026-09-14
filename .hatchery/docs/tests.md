<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Tests</h1>
<br clear="both">

pytest test suite for Hatchery.

<br>

## Contents

- [Contents](#contents)
- [Structure](#structure)
- [Running Tests](#running-tests)
- [CI](#ci)
- [Adding Tests](#adding-tests)

---

<br>

## Structure

```
tests/
├── test_providers.py          — libvirt provider (KVM/QEMU); Hyper-V TBD
├── test_nest_transport.py     — Nest SSH control plane (#218); mocked ssh
├── test_config.py             — application config and data directory
├── test_answerfile.py         — answer file generation (OS-aware)
└── test_provision.py          — post-install guest provisioning
```

Tests mirror the structure of `lib/`. Every module in `lib/` should have a corresponding test file.

<br>

---

<br>

## Running Tests

Install dev dependencies once:

```bash
uv sync
```

Run the full suite from the repo root:

```bash
uv run pytest
```

Run with coverage:

```bash
uv run pytest --cov --cov-report=term-missing
```

Run a single file:

```bash
uv run pytest tests/test_config.py
```

<br>

---

<br>

## CI

GitHub Actions runs on every PR and push to `main` (path-filtered):

| Check | Where | Tool |
|---|---|---|
| Lint | `ubuntu-latest` | `ruff check .` + `ruff format --check .` |
| Tests | **Matrix:** `ubuntu-latest`, `macos-latest`, `windows-latest` | `pytest -m "not hypervisor"` with coverage |

### Multi-OS test matrix (#203)

Portable unit/integration tests must pass on **all three** host OS runners. The coverage gate is the project default (`--cov-fail-under=90` in `pyproject.toml`) on **each** OS. Coverage XML is uploaded per OS as `coverage-<runner>`.

| Suite | CI | When to use |
|---|---|---|
| Default (no mark) | Yes — all three OSes | Mocked providers, Nest transport, Flask, library, etc. |
| `@pytest.mark.hypervisor` | **No** — excluded via `-m "not hypervisor"` | Needs a real Nest (libvirt/UTM/Hyper-V). Run locally when the Nest is available. |

Optional tools (e.g. `pwsh` for PowerShell syntax checks) may `skipif` when absent; that is fine on CI.

Some **libvirt-only** unit tests that assert POSIX file mode bits (`chmod` world-read/execute for `libvirt-qemu`) are skipped on Windows (`sys.platform == "win32"`). macOS/Linux runners still execute them. Broader per-OS requirements live in [#208](https://github.com/dustinestes/Hatchery/issues/208).

The import-time background sync thread is stopped in `tests/conftest.py` so long Windows runs do not race host requirement alerts into the test DB after `bg_interval`.

Both lint and the full OS matrix must pass before merge.

<br>

---

<br>

## Adding Tests

1. Create or open the test file mirroring the module: `lib/foo.py` → `tests/test_foo.py`
2. Use `pytest` fixtures for Flask app context where needed (`app.test_client()`)
3. Mock `subprocess` calls for VM operations — default tests must not require a real Nest
4. Mark tests that need a live hypervisor with `@pytest.mark.hypervisor` (excluded from multi-OS CI)
5. Use `pytest.mark.parametrize` for multiple OS type variants

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
