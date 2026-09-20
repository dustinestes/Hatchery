# ADR-0014: Optional Local Nest and empty Nest registry

- **Status:** Accepted
- **Date:** 2026-09-20
- **Issues:** [#266](https://github.com/dustinestes/Hatchery/issues/266) (epics [#336](https://github.com/dustinestes/Hatchery/issues/336), [#202](https://github.com/dustinestes/Hatchery/issues/202))
- **How-to:** [architecture-nests.md](../architecture-nests.md); launch: [docs/cli/serve.md](../cli/serve.md)
- **Related:** [ADR-0003](0003-nest-registry-provider-factory.md), [ADR-0005](0005-controller-only-package-distribution.md), [ADR-0013](0013-hatchery-cli-launch-and-operator.md)

## Context

ADR-0005 requires a fresh Controller install to start with **no Nests registered**. The Nest registry still force-inserted id `local` on every DB migrate and re-inserted it via `ensure_local_nest` on boot and many request paths. That blocked Controller-only workstations, empty sandboxes, and package-manager installs that must not assume a Local Nest hypervisor.

Contributors and launch configs also need a **session opt-in** to register this Controller device as a Local Nest without editing Settings.

## Decision

1. **Empty registry by default.** Fresh data dirs do not insert Nest id `local`. Existing databases that already have `local` keep it (no auto-cull).
2. **Local Nest is optional.** At most one Nest with `location=local`, and only id `local` may use that location. Operators may remove all Nests, including Local, via Settings.
3. **Add Local later.** Settings exposes **Add Local Nest** when `local` is absent. `ensure_local_nest()` remains the single INSERT helper (libvirt / Local / id `local`).
4. **Session Local Nest registration.** `hatchery serve --nest-local` and env `HATCHERY_NEST_LOCAL` (truthy `1` / `true` / `yes`) call `ensure_local_nest()` once at Controller boot. **Idempotent:** if id `local` already exists, no-op (do not fail). Session-only; never written to Settings or bootstrap YAML (same rule as `--data-dir` in ADR-0013).
5. **Default Nest selection.** When a Nest id is omitted: if exactly one Nest is registered, it may be the default; if zero or many, require explicit selection (empty-state UX or clear error). Do not hard-wire `local`.
6. **Reserve “seed” for data injection.** CLI/docs do **not** use “seed” for Nest registration. Future launch-time fixture loading (YAML that pushes Settings, connections, or test data into the DB) may use `seed` language; that is out of scope here. A later `--nest-remote` (values or prompts) may mirror `--nest-local` without implying bulk data load.

## Consequences

**Good**

- Implements ADR-0005 empty-registry north star in running code
- Controller-only and Controller+Local sandboxes via `--data-dir` +/- `--nest-local`
- Launch configs (#337) can wire the same flag without a second registration mechanism
- Clear room for future `--nest-remote` and a real `seed` surface

**Neutral / follow-on**

- VS Code / Cursor launch.json trio (#337)
- Operator CLI Nest targeting (#23) already matches this default rule (ADR-0013)

**Bad / accepted cost**

- Call sites that assumed `local` always exists must use `default_nest_id()` or empty-state paths
- Contributor muscle memory of “boot always has Local” changes; docs and `--nest-local` cover the old path

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep migrate-time insert; only hide Local in UI | Still fails ADR-0005 and Controller-only package installs |
| Register Local only on first Settings open | Surprises operators; couples UX to registry mutation |
| Persist Nest registration preference in Settings | Breaks disposable sandboxes; conflates session with persistence |
| `--seed-local-nest` naming | “Seed” implies filling DB with fixtures/data; reserve that word for real fixture load |
| Fail boot when `local` already exists under `--nest-local` | Breaks restart / launch.json; idempotent ensure is enough |
