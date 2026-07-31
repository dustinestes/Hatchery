# Hatchery

A local web application for creating, provisioning, and managing VMs on an Ubuntu host using QEMU/KVM (libvirt). Built Windows-first in v1.

**Agent instructions** for Cursor live in [`.cursor/rules/`](.cursor/rules/). Do not duplicate those conventions here — that file set is the source of truth for agents.

| Rule | Applies | Covers |
|---|---|---|
| `hatchery-core.mdc` | Always | Naming, design constraints |
| `git-workflow.mdc` | Always | Portable issue → branch → PR |
| `accessibility.mdc` | Always | Inclusive UI — keyboard, labels, focus, contrast |
| `python-style.mdc` | `**/*.py`, `pyproject.toml` | ruff, uv, tests |
| `providers-and-automation.mdc` | Provider / answerfile / provision paths | Hypervisor + automation patterns |

Human-oriented docs:

- Setup and contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Product overview: [`README.md`](README.md)
- Project meta (branding, docs, audits): [`.hatchery/`](.hatchery/)

## Quick start

```bash
uv sync
uv run gunicorn hatchery:app --bind 127.0.0.1:5000 --workers 1
# http://localhost:5000
```

Host packages and full setup notes are in `CONTRIBUTING.md`.
