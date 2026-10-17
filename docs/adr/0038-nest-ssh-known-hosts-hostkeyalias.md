# ADR-0038: Nest SSH known_hosts under data_dir keyed by Nest id

- **Status:** Accepted
- **Date:** 2026-10-17
- **Issues:** [#594](https://github.com/dustinestes/Hatchery/issues/594)
- **Related:** [ADR-0029](0029-guest-ssh-bootstrap-and-guest-transport.md), [ADR-0030](0030-controller-remoting-identities.md), [ADR-0037](0037-guest-ssh-known-hosts-hostkeyalias.md) (guest plane sibling)
- **How-to:** [nest-transport.md](../nest-transport.md), [nest-ssh.md](../nest-ssh.md)

## Context

Remote Nest SSH honored per-Nest `known_hosts` policy (`default` | `accept-new` | `skip`) but still used the operator personal `~/.ssh/known_hosts` as `UserKnownHostsFile`. Guest plane already moved to a Hatchery-owned file under `data_dir` (ADR-0037). Nest and Guest must stay separate trust stores (ADR-0029). Nest host/IP reuse across labs (or Nest reinstall with a new host key at the same address) can collide in personal known_hosts the same way guest DHCP did.

## Decision

1. **Hatchery-owned Nest trust file:** Controller OpenSSH Nest client uses  
   `{data_dir}/remoting/known_hosts/nest` as `UserKnownHostsFile`, with `GlobalKnownHostsFile=/dev/null`, so personal and system known_hosts are not consulted for Nest remoting (unless `known_hosts=skip`, which keeps null known_hosts).
2. **Reuse Nest row policy:** Do not invent a second policy enum. Apply the Nest connection's existing `known_hosts` value against the Hatchery Nest file.
3. **Key by Nest registry id:** Pass `HostKeyAlias=<nest.id>` from `to_connection_config` / `NestSshConfig.host_key_alias`. Trust entries follow Nest identity, not bare recycled Nest IPs. Ad-hoc probes without a Nest id omit the alias and fall back to hostname/IP entries in the same Hatchery file.
4. **Planes stay separate:** Do not merge Nest and Guest known_hosts files. Guest remains `{data_dir}/remoting/known_hosts/guest` (ADR-0037).
5. **Remove hygiene:** Best-effort `ssh-keygen -R <nest.id>` against the Nest file when a Nest is removed from the registry (`replace_nests`). Alias + Hatchery file are the durable guard; prune is cleanup only.

## Consequences

- Operators’ `~/.ssh/known_hosts` is untouched by Nest remoting.
- Lab Nest IP reuse no longer collides Nest trust when Nest ids differ.
- First connect with `known_hosts=default` and an empty Hatchery file still fails under BatchMode until the operator uses `accept-new` once (or pins the key) - same OpenSSH semantics as before, against the Hatchery file.
- Nest delete should prune alias entries so re-adding the same Nest id with a new host key can accept-new cleanly.

## Alternatives considered

- **Alias by host:port only:** Rejected as primary key; Nest id is stable across host/IP edits in Settings. Hostname still used when Nest id is absent (draft probes).
- **Share guest known_hosts file:** Rejected; ADR-0029 planes stay separate.
- **Default Nest policy to `skip`:** Rejected as default MITM weaken; Nest row policy stays operator-chosen.
