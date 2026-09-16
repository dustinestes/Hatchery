<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Nest SSH Identity Expiry</h1>
<br clear="both">

How Hatchery alerts when a Nest SSH identity is nearing expiry — without storing private keys.

<br>

## Contents

- [Contents](#contents)
- [Expiry Sources](#expiry-sources)
- [Alert Tiers](#alert-tiers)
- [Tracked Identities](#tracked-identities)
- [Alerts](#alerts)
- [Testing](#testing)

---

<br>

## Expiry Sources

| Material | Expiry in file? |
|---|---|
| Normal OpenSSH private/public key | **No** — set Identity expiry on the Nest row |
| OpenSSH **certificate** | **Yes** — `Valid before` via `ssh-keygen -L` |
| Operator policy date | **Yes** — `identity_expires_at` on the Nest |

Hatchery never invents an expiry for a plain key. If Identity expiry is omitted and a certificate path is available (`cert_path` or `identity_file-cert.pub`), Valid-before may be used.

<br>

## Alert Tiers

Configured in Settings → Security. Use **+ Add tier** to add a row, then fill **Days before** and **Alerts per day** (numeric fields). The tightest matching window wins. Checks run on the background validation interval.

Example: within 30 days, once per day; within 7 days, twice per day.

<br>

## Tracked Identities

SSH identity **paths** and optional **expiry** live on each Nest under Settings → Nests (`identity_file`, `cert_path`, `identity_expires_at`). Hatchery is the SSH client: point the Nest row at a private key path on the Hatchery host, and trust the matching public key on the Nest (`authorized_keys`).

Private key bytes are not stored — only paths and policy dates. The legacy Security JSON list (`nest_ssh_identities`) is cleared on upgrade; alert evaluation reads Nest rows via `lib/nests.identities_for_expiry()`.

<br>

## Alerts

Messages use a stable prefix: `Nest SSH identity expiry:`. They appear in the Alerts pane. Updating Identity expiry past all tier windows resolves prior alerts for that Nest id.

Module: [`lib/nest_key_expiry.py`](../../lib/nest_key_expiry.py).

<br>

## Testing

You do not need a special key file for a quick test. Plain OpenSSH keys have no in-file expiry — setting Identity expiry on a remote Nest row is enough.

### Fast path (manual Identity expiry)

1. Settings → Nests → expand a remote Nest (or add one)
2. Set **Identity file** to any path string (need not exist for alert-only tests)
3. Set **Identity expiry** to a day inside a Security tier window
4. Save; wait for the background interval (or restart Hatchery)

### Certificate Valid-before

Omit Identity expiry and set **Certificate path** (or rely on `identity_file-cert.pub` beside the key). Hatchery reads **Valid before** via `ssh-keygen -L` when available.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
