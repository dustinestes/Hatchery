<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
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
├── test_providers.py          - libvirt provider (KVM/QEMU); Hyper-V TBD
├── test_factory.py            - Nest id → BaseProvider factory (#206)
├── test_nest_transport.py     - Nest SSH control plane (#218); mocked ssh
├── test_config.py             - application config and data directory
├── test_answerfile.py         - answer file generation (OS-aware)
└── test_provision.py          - post-install guest provisioning
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

| Check | Where | Tool | Blocks PR merge? |
|---|---|---|---|
| Lint | `ubuntu-latest` | `ruff check .` + `ruff format --check .` | Yes |
| Tests | `ubuntu-latest`, `macos-latest` | `pytest -m "not hypervisor"` with coverage | Yes |
| Tests | `windows-latest` | same portable suite | **No** ([#400](https://github.com/dustinestes/Hatchery/issues/400)) - still runs; failure alerts fire |

### Multi-OS test matrix (#203 / #400)

Portable unit/integration tests still run on **all three** host OS runners. **PR merge** waits on lint + ubuntu + macos. Windows runs in parallel on the PR (and again on the post-merge `push` to `main`); a red Windows job fails that Actions run so notifications still arrive - open a follow-up `fix` PR if needed. Coverage gate is the project default (`--cov-fail-under=90` in `pyproject.toml`) on each OS. Coverage XML is uploaded per OS as `coverage-<runner>`.

| Suite | CI | When to use |
|---|---|---|
| Default (no mark) | Yes - all three OSes | Mocked providers, Nest transport, Flask, library, etc. |
| `@pytest.mark.hypervisor` | **No** - excluded via `-m "not hypervisor"` | Needs a real Nest (libvirt/UTM/Hyper-V). Run locally when the Nest is available. |

Optional tools (e.g. `pwsh` for PowerShell syntax checks) may `skipif` when absent; that is fine on CI.

Some **libvirt-only** unit tests that assert POSIX file mode bits (`chmod` world-read/execute for `libvirt-qemu`) are skipped on Windows (`sys.platform == "win32"`). macOS/Linux runners still execute them. Broader per-OS requirements live in [#208](https://github.com/dustinestes/Hatchery/issues/208).

The import-time hatch status poller and validator scheduler are stopped in `tests/conftest.py` so long Windows runs do not race host requirement alerts into the test DB.

**Before merge:** lint + `pytest (ubuntu-latest)` + `pytest (macos-latest)`. Windows is advisory on the PR (and re-checked after merge to `main`).

<br>

---

<br>

## Adding Tests

1. Create or open the test file mirroring the module: `lib/foo.py` → `tests/test_foo.py`
2. Use `pytest` fixtures for Flask app context where needed (`app.test_client()`)
3. Mock `subprocess` calls for VM operations - default tests must not require a real Nest
4. Mark tests that need a live hypervisor with `@pytest.mark.hypervisor` (excluded from multi-OS CI)
5. Use `pytest.mark.parametrize` for multiple OS type variants

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
