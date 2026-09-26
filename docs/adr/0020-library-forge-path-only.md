# ADR-0020: Library connections without classic git clone

- **Status:** Accepted
- **Date:** 2026-09-26
- **Issues:** [#406](https://github.com/dustinestes/Hatchery/issues/406); disable/excise pre-work for [#379](https://github.com/dustinestes/Hatchery/issues/379) / [ADR-0019](0019-library-disable-excise.md)
- **Supersedes:** [ADR-0009](0009-library-git-checkout-cache.md)
- **Related:** [ADR-0010](0010-library-forge-providers.md) (forge HTTP), [ADR-0016](0016-library-operator-plane.md)
- **How-to:** [library.md](../library.md)

## Context

ADR-0009 kept a Controller shallow clone at `{data_dir}/library/git/{connection_id}/` for Library `type: git`. Forge connections ([ADR-0010](0010-library-forge-providers.md)) list and pull over HTTP with **no** working tree. Dual-run left classic git past usefulness; operators should use **forge** (remote SCM) or **path** (local/share trees).

## Decision

1. Supported connection types: **`path`**, **`https`**, **`api`**, **`forge`** only. **`type: git` is removed.**
2. Do **not** create or refresh `{data_dir}/library/git/`. Delete clone-cache helpers and UI (including “delete git clone cache” on connection remove).
3. Legacy DB rows with `type: git`: **refuse** test / list / pull / tip with a clear error; **reject** create/update as git; allow **delete** (and remove leftover clone dirs if present). Do **not** auto-migrate to forge (URI shapes differ) or silently disable.
4. After no git rows remain, migrate the SQLite `CHECK` to drop `'git'` from the type enum.
5. Digest kind **`git_blob`** (content hashing) remains - it is forge/path identity, not classic `type: git`.

## Consequences

**Good**

- One remote-SCM story (forge); no Controller clone disk/network tax
- Clear Connections / remove flows no longer special-case clone cache ([ADR-0019](0019-library-disable-excise.md))

**Neutral / follow-on**

- Operators with old git connections must recreate as forge or path
- Additional forge providers (#310–#312) expand coverage; GitHub forge + path is enough to retire clones

**Bad / accepted cost**

- Breaking for any still-using `type: git` configs

## Alternatives

| Alternative | Why not |
|---|---|
| Keep dual-run forever | Clone path is obsolete once forge exists for the same remotes |
| Auto-convert git → forge | SSH / file URLs and non-GitHub hosts do not map safely |
| Auto-disable git rows | Leaves invalid types in the registry |
