# ADR-0044: Free HEAD is Local Nest only (no Nest SSH product)

- **Status:** Accepted
- **Date:** 2026-11-11
- **Issues:** [#620](https://github.com/dustinestes/Hatchery/issues/620), [#345](https://github.com/dustinestes/Hatchery/issues/345)
- **Related:** [ADR-0042](0042-open-core-public-and-enterprise-tier.md), [ADR-0046](0046-nest-is-hardware-multi-provider.md) (Nest = hardware; many Local providers), [ADR-0038](0038-nest-ssh-known-hosts-hostkeyalias.md) (superseded for free Nest plane)

## Context

Free `main` shipped unfinished Remote Nest / Nest SSH product surfaces (registry `location=remote`, `lib/nest_transport.py`, Connections remote UX, Nest known_hosts). That confused Local-only operators and conflicted with open-core: Enterprise Remote Nest north star is **Nest Agent**, not reviving Nest SSH as a paid MVP.

Guest remoting (SSH/WinRM to known guest VMs) remains a free plane and must not be gutted with Nest-plane SSH.

## Decision

On free Hatchery HEAD:

1. Nest registry accepts **Local Nest only** (id `local`, `location=local`). Empty registry remains valid (ADR-0014).
2. Remove Nest-plane SSH/WinRM transport product (`lib/nest_transport.py` and Nest known_hosts prune/path under Nest trust).
3. UI/CLI/docs must not teach Add Remote Nest / Nest SSH as free onboarding.
4. Schema columns for remote Nest fields may remain dormant for DB compatibility; product paths refuse remote create/update.
5. Enterprise Remote Nest hierarchy ships later via Nest Agent (#345), not by restoring Nest SSH on free.

## Consequences

- Operators get a clear Local Nest free product; Remote Nest is documented under [`docs/enterprise/`](../enterprise/).
- Existing DBs with remote rows: list may still show historical rows; factory/ops refuse them until removed.
- ADR-0038 Nest SSH known_hosts is **Superseded** for free HEAD; guest known_hosts (ADR-0037) stays.
- Shared OpenSSH client (`lib/openssh_client.py`) and remoting identities catalog remain for **guest** plane.

## Alternatives

- Gate remote Nest UI behind Enterprise extension without deleting Nest SSH: rejected for free HEAD honesty (half-built SSH still ships).
- Keep Nest SSH as free: rejected (ADR-0042 / Agent north star).
