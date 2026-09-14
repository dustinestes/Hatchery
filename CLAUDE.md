# Hatchery

A local web application for creating, provisioning, and managing VMs. **Host plane** runs on Linux / macOS / Windows; **Nest plane** is libvirt / UTM / Hyper-V (local or remote). Built Windows-guest-first in v1. Architecture: [`.hatchery/docs/architecture-nests.md`](.hatchery/docs/architecture-nests.md).

**Agent instructions** for Cursor live in [`.cursor/rules/`](.cursor/rules/). Do not duplicate those conventions here — that file set is the source of truth for agents.

| Rule | Applies | Covers |
|---|---|---|
| `hatchery-core.mdc` | Always | Naming, design constraints |
| `git-workflow.mdc` | Always | Portable issue → branch → PR |
| `accessibility.mdc` | Always | Inclusive UI — keyboard, labels, focus, contrast |
| `cross-platform.mdc` | Always | Host vs Nest planes; multi-OS CI || `python-style.mdc` | `**/*.py`, `pyproject.toml` | ruff, uv, tests |
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
