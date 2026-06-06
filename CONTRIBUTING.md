<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset=".hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src=".hatchery/branding/icons/hatchery-icon-light.svg" height="40" alt="Hatchery">
</picture>
<h1>Contributing</h1>
<br clear="both">

Thanks for your interest in contributing. Hatchery is a focused project and contributions are welcome — whether that's a bug fix, a new feature, documentation improvements, or just opening an issue with a thoughtful idea.

<br>

## Contents

- [Contents](#contents)
- [Ways to Contribute](#ways-to-contribute)
- [Before You Open a PR](#before-you-open-a-pr)
- [Development Setup](#development-setup)
- [Code & Style Guidelines](#code--style-guidelines)
- [Commit Messages](#commit-messages)
- [Questions](#questions)

---

<br>

## Ways to Contribute

- **Bug reports** — something broken or behaving unexpectedly? Open an issue.
- **Feature requests** — have an idea that fits the project's direction? Open an issue and describe the use case.
- **Pull requests** — fixes, improvements, or new functionality. See the process below.
- **Documentation** — clearer explanations, better examples, or corrected typos are always appreciated.

---

<br>

## Before You Open a PR

1. **Check existing issues and PRs** to avoid duplicating work in progress.
2. **Open an issue first** for anything significant — a new provider, a change to the answer file schema, or a new provisioning target. This keeps effort aligned before code is written.
3. **Keep PRs focused.** One concern per pull request makes review faster and merging cleaner.

---

<br>

## Development Setup

No build tooling required. Clone the repo, create a virtual environment, and install dependencies.

```bash
git clone https://github.com/dustin-estes/hatchery.git
cd hatchery
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

**Host dependencies** (Ubuntu):

```bash
sudo apt install qemu-kvm libvirt-daemon-system virt-manager virtinst \
    libguestfs-tools swtpm swtpm-tools
```

**Run the app:**

```bash
python app.py
# http://localhost:5000
```

### A note on devcontainers

Hatchery does not ship devcontainer configurations. The app requires direct access to the host's libvirt daemon and KVM stack (`virsh`, `virt-install`, `qemu-img`). A container cannot reach these host-level services without privileged container configuration that adds significant complexity for no practical gain. Run Hatchery directly on your Ubuntu host.

---

<br>

## Code & Style Guidelines

- **Python** — formatted and linted with `ruff`. Run `ruff check . && ruff format --check .` before pushing.
- **Line length** — 100 characters.
- **HTML/CSS/JS** — follow the existing patterns in `templates/ui/` and `static/`. No frameworks.
- **Providers** — new hypervisor integrations go in `lib/providers/` and implement the interface in `base.py`. Don't add methods to the interface unless the feature genuinely requires it.
- **Answer files** — new guest OS types get a template under `templates/answerfiles/` and a corresponding branch in `answerfile.py`.
- **Comments** — write one only when the *why* is non-obvious. Don't describe what the code does.

---

<br>

## Commit Messages

Use a conventional commit prefix followed by a short, present-tense description:

```
feat: add snapshot list to manage page
fix: resolve virsh timeout on slow hosts
docs: update getting-started with VirtIO setup
chore: pin ruff version in requirements-dev
breaking: rename /api/vms to /api/brood
```

| Prefix | When to use |
|---|---|
| `feat:` | New feature or user-facing change |
| `fix:` | Bug fix |
| `docs:` | Documentation changes only |
| `chore:` | Maintenance, tooling, or non-functional changes |
| `refactor:` | Code restructure with no behavior change |
| `sec:` | Security fix or audit finding |
| `breaking:` | Change that breaks backwards compatibility |

---

<br>

## Questions

Open an issue and tag it `question`. There's no wrong question here.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset=".hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src=".hatchery/branding/logos/hatchery-logo-light.svg" height="32" alt="Hatchery">
</picture>
<div align="right">hatch, provision, and manage VMs</div>
<br clear="both">
