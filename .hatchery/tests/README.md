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
├── test_providers/
│   ├── test_libvirt.py       — libvirt provider (KVM/QEMU)
│   └── test_hyperv.py        — Hyper-V remote provider (future)
├── test_answerfile.py         — answer file generation (OS-aware)
└── test_provision.py          — post-install provisioning
```

Tests mirror the structure of `lib/`. Every module in `lib/` should have a corresponding test file.

<br>

---

<br>

## Running Tests

Install dev dependencies once:

```bash
pip install -r requirements-dev.txt
```

Run the full suite from the repo root:

```bash
pytest tests/
```

Run with coverage:

```bash
pytest tests/ --cov --cov-report=term-missing
```

Run a single file:

```bash
pytest tests/test_answerfile.py
```

<br>

---

<br>

## CI

The test workflow runs on every PR and push to `main`:

| Check | Tool |
|---|---|
| Lint | `ruff check .` + `ruff format --check .` |
| Tests | `pytest tests/ --cov --cov-fail-under=60` |

Both must pass before merge.

<br>

---

<br>

## Adding Tests

1. Create or open the test file mirroring the module: `lib/foo.py` → `tests/test_foo.py`
2. Use `pytest` fixtures for Flask app context where needed (`app.test_client()`)
3. Mock `subprocess` calls for VM operations — tests should not require a real KVM host
4. Use `pytest.mark.parametrize` for multiple OS type variants

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Where environments hatch</div>
<br clear="both">
