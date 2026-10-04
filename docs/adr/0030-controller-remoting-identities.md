# ADR-0030: Controller remoting identities (Nest + Guest SSH keys)

- **Status:** Accepted
- **Date:** 2026-10-04
- **Issues:** [#519](https://github.com/dustinestes/Hatchery/issues/519) (planning)
- **Implementation / follow-on:** [#522](https://github.com/dustinestes/Hatchery/issues/522) (catalog + validators + CLI), [#523](https://github.com/dustinestes/Hatchery/issues/523) (Nest binding), [#524](https://github.com/dustinestes/Hatchery/issues/524) (guest authorize). IA follow-ons (not this ADR): [#525](https://github.com/dustinestes/Hatchery/issues/525)–[#529](https://github.com/dustinestes/Hatchery/issues/529)
- **Related:** [ADR-0029](0029-guest-ssh-bootstrap-and-guest-transport.md) (bootstrap / planes; keys deferred here), [ADR-0022](0022-dual-surface-operator-discipline.md), [#497](https://github.com/dustinestes/Hatchery/issues/497) (`guest_transport`), [#156](https://github.com/dustinestes/Hatchery/issues/156) (ephemeral admin), [#110](https://github.com/dustinestes/Hatchery/issues/110) / [#259](https://github.com/dustinestes/Hatchery/issues/259) (secrets)
- **How-to:** [guest-transport.md](../guest-transport.md), [nest-transport.md](../nest-transport.md), [schema/database.md](../schema/database.md) (planned table sketch)

## Context

Guest remoting (#497) authenticates with hatch admin password over SSH (`sshpass` / `SSH_ASKPASS`) or WinRM. Nest remoting uses a per-Nest `identity_file` path on the Nest row. ADR-0029 deferred Controller→guest key identity and forbade silently reusing Nest keys on guests.

Operators need:

- A Hatchery-managed key with clear lifecycle
- Optional operator path-referenced keys
- Explicit binding for Nest and Guest (no round-robin)
- Key-required guest SSH after authorize, without breaking first-boot chicken-egg
- Shared OpenSSH **client** helpers; separate Nest vs Guest transport modules

Legacy Settings JSON `nest_ssh_identities` was already cleared in favor of Nest-row paths. Putting a new catalog back into `app_settings` would fight [ADR-0022](0022-dual-surface-operator-discipline.md).

## Decision

### 1. First-class remoting identity catalog (system of record)

Persist identities in a dedicated SQLite table (product graph), not `app_settings`. UI may live under Settings → Security (or a Remoting pane); CLI is a product noun (sketch: `hatchery remoting-identity …`).

| Kind | Private key | Public key | Lifecycle |
|---|---|---|---|
| `hatchery` (managed) | Under Controller `data_dir` (e.g. `remoting/hatchery_ed25519`); mode `0600`; generate if missing | Derived `.pub` | Create / rotate / revoke via CLI+UI |
| `path` (operator) | Operator path on Controller | Matching `.pub` or stored pubkey text | Register path + optional cert path / expiry |

**Never store private key bytes in the database** - path references only (same Nest convention). Encryption of other secrets stays #110 / #259.

### 2. Explicit binding (reject round-robin)

| Consumer | Binding |
|---|---|
| Remote Nest | `remoting_identity_id` (dropdown of validator-backed identities) + Nest-specific `ssh_user` as needed. Cert/expiry live on the identity record, not duplicated per Nest. |
| Guest / Clutch | `remoting.ssh.authorize: [identity_id, …]` and optional port |

Do **not** try registered keys until one works. Nest `identity_file` is **never** auto-copied into guest authorize; the same Controller **pubkey** may be authorized on Nest and guest only when that identity id is explicitly bound on both.

### 3. Shared helpers; separate transport modules

| Shared | Separate |
|---|---|
| [`lib/openssh_client.py`](../../lib/openssh_client.py) (argv, run, copy) | `lib/nest_transport.py` vs `lib/guest_transport.py` |
| `lib/remoting_identities.py` (catalog resolve → path) | Nest vs Guest credentials and authorize lists |

### 4. Guest SSH auth policy (key-required after authorize)

1. First-boot brings `sshd` up (ADR-0029 MSI path); hatch may still use password until keys are installed.
2. Inject authorized pubkeys from Clutch `remoting.ssh.authorize` (default new Clutches: Hatchery-managed identity).
3. Controller verifies key SSH via `guest_transport` (BatchMode + identity path).
4. **Then** disable guest SSH `PasswordAuthentication`.
5. WinRM may still use hatch password for Windows fallback until [#156](https://github.com/dustinestes/Hatchery/issues/156).

Empty `authorize` is invalid for SSH hatch after implementation lands. Disabling password SSH **before** pubkey install is rejected (chicken-egg).

### 5. Validators

Generalize Nest key expiry ([`nest_key_expiry`](../../lib/validators/builtins.py)): identity file exists, permissions, pubkey derivable, optional cert Valid-before / expiry tiers, Nest and Clutch bindings resolve. Register as validators; do not grow a private loop in `hatchery.py`.

### 6. Field sketch (implementation children)

**Table `remoting_identities` (planned):**

| Column | Notes |
|---|---|
| `id` | Stable text id |
| `name` | Display label |
| `kind` | `hatchery` \| `path` |
| `identity_file` | Absolute or `data_dir`-relative path; never key bytes |
| `pubkey` | Optional cached OpenSSH pubkey line |
| `cert_path` | Optional |
| `identity_expires_at` | Optional operator policy date |
| `created_at` / `updated_at` | ISO timestamps |

**Nest row:** add `remoting_identity_id`; migrate existing `identity_file` / `cert_path` / `identity_expires_at` into catalog rows where practical; prefer identity id going forward.

**Clutch VM (YAML sketch):**

```yaml
remoting:
  ssh:
    port: 22
    authorize:
      - hatchery   # identity id; default when omitted at authoring time after impl
```

## Consequences

- One catalog for Nest and Guest; operators bind explicitly.
- Guest hatch can drop password SSH after verify; WinRM/password hatch window remains until #156.
- ADR-0029 section 4 (keys deferred) is superseded by this ADR for identity product shape.
- UI IA for Nest Connections / VM Inventory stickies is **out of this ADR** (separate issues from #519 planning).

## Alternatives considered

| Option | Why not |
|---|---|
| Round-robin keys until one works | Noisy, weak audit, against OpenSSH practice |
| Catalog in `app_settings` / revive `nest_ssh_identities` | Fights ADR-0022; Nest already left that shape |
| Silent Nest key → guest authorize | Violates Nest ≠ Guest plane (ADR-0029) |
| Private key bytes in SQLite | Path reference convention; secrets epic later |
| Keys required with password disabled before inject | Breaks first-boot remoting |
| Merge Nest and Guest transport modules | Different targets and configs (ADR-0021) |
