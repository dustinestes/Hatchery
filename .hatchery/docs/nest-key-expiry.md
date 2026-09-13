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
| Normal OpenSSH private/public key | **No** — set `expires_at` manually |
| OpenSSH **certificate** | **Yes** — `Valid before` via `ssh-keygen -L` |
| Operator policy date | **Yes** — `expires_at` on the tracked identity |

Hatchery never invents an expiry for a plain key. If `expires_at` is omitted and a certificate path is available (`cert_path` or `identity_file-cert.pub`), Valid-before may be used.

<br>

## Alert Tiers

Configured in Settings → Security. Use **+ Add tier** to add a row, then fill **Days before** and **Alerts per day** (numeric fields). The tightest matching window wins. Checks run on the background validation interval.

Example: within 30 days, once per day; within 7 days, twice per day.

<br>

## Tracked Identities

Until the Nest registry ships, identities are listed in Settings as JSON (`nest_ssh_identities`):

```json
[
  {
    "id": "hyperv-lab",
    "label": "Hyper-V lab Nest",
    "identity_file": "~/.ssh/nest_ed25519",
    "expires_at": "2026-12-01T00:00:00+00:00",
    "expires_source": "manual"
  }
]
```

Private key bytes are not stored — only paths and policy dates.

<br>

## Alerts

Messages use a stable prefix: `Nest SSH identity expiry:`. They appear in the Alerts pane. Updating `expires_at` past all tier windows resolves prior alerts for that identity id.

Module: [`lib/nest_key_expiry.py`](../../lib/nest_key_expiry.py).

<br>

## Testing

You do not need a special key file for a quick test. Plain OpenSSH keys have no in-file expiry — setting `expires_at` in Settings is enough.

### Fast path (manual `expires_at`)

1. Open **Settings → Security**.
2. Keep or add alert tiers (for example 30 days / 1 per day, and 7 days / 2 per day).
3. In **Nest SSH identities (JSON)**, use an identity whose `expires_at` falls inside a tier window:

```json
[
  {
    "id": "test-nest",
    "label": "Test Nest",
    "expires_at": "2026-09-20T00:00:00+00:00",
    "expires_source": "manual"
  }
]
```

Choose a date within your configured **Days before** windows (for example about a week out if you have a 7-day tier).

4. Save. Expiry sync runs on save and again on the background validation interval.
5. Open **Notifications → Alerts** and look for a message starting with `Nest SSH identity expiry:`.

No `identity_file` is required for this path.

### Optional: OpenSSH certificate Valid-before

Use this only to exercise cert parsing (omit `expires_at`, set `cert_path` or rely on `identity_file-cert.pub`):

```bash
# One-time CA + Nest key
ssh-keygen -t ed25519 -f /tmp/hatchery-test-ca -N "" -C "test-ca"
ssh-keygen -t ed25519 -f /tmp/hatchery-test-nest -N "" -C "test-nest"

# Certificate valid for 14 days (adjust -V as needed)
ssh-keygen -s /tmp/hatchery-test-ca -I hatchery-test -n hatchery \
  -V +14d /tmp/hatchery-test-nest.pub
# Writes /tmp/hatchery-test-nest-cert.pub
```

Then in identities JSON:

```json
[
  {
    "id": "cert-nest",
    "label": "Cert Nest",
    "identity_file": "/tmp/hatchery-test-nest",
    "cert_path": "/tmp/hatchery-test-nest-cert.pub",
    "expires_source": "cert"
  }
]
```

Omit `expires_at` so Hatchery reads **Valid before** via `ssh-keygen -L`.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
