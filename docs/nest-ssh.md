<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Nest SSH</h1>
<br clear="both">

How to trust a Hatchery Controller on a Remote Nest over SSH: remoting identities, Nest `authorized_keys`, known_hosts, Test Nest connection, and troubleshooting.

For the transport contract (SSH vs WinRM, connectivity stages), see [Nest transport](nest-transport.md). For a short operator path, see [Getting Started - Add a Remote Nest](getting-started.md#add-a-remote-nest).

<br>

## Contents

- [Contents](#contents)
- [Roles](#roles)
- [Remoting identities](#remoting-identities)
- [Authorize the Nest](#authorize-the-nest)
- [Register and test](#register-and-test)
- [Known hosts](#known-hosts)
- [Identity expiry](#identity-expiry)
- [Troubleshooting](#troubleshooting)

---

<br>

## Roles

| Side | Role |
|---|---|
| **Hatchery Controller** | SSH **client**. Holds private keys (path references in the remoting identities catalog). Never stores Nest private keys. |
| **Nest** | SSH **server**. Trusts the Controller public key in `authorized_keys` (or Windows `administrators_authorized_keys`). Runs the hypervisor (libvirt / UTM / Hyper-V). |

Nest transport and Guest transport are separate planes. Do not copy a Nest remoting identity into guest `remoting.ssh.authorize` by default ([ADR-0030](adr/0030-controller-remoting-identities.md)).

<br>

## Remoting identities

Controller catalog: Settings → **Security** (remoting identities), or:

```bash
uv run hatchery remoting-identity generate
uv run hatchery remoting-identity show hatchery
uv run hatchery --json remoting-identity show hatchery
```

Copy the **public** key line from the UI (expanded Hatchery identity row) or from `show` / JSON `pubkey`. The private key stays on the Controller under the data dir (managed) or an operator path (path identities).

<br>

## Authorize the Nest

On a **Windows Hyper-V Nest**, prefer the Hatchery Library scripts (pull or download):

| Script | Purpose |
|---|---|
| [`authorize-hatchery-nest-ssh-windows.ps1`](https://github.com/dustinestes/Hatchery-Library/blob/main/scripts/windows/authorize-hatchery-nest-ssh-windows.ps1) | Ensure OpenSSH Server + firewall TCP 22; append Controller pubkey |
| [`enable-hyperv-windows.ps1`](https://github.com/dustinestes/Hatchery-Library/blob/main/scripts/windows/enable-hyperv-windows.ps1) | Enable Hyper-V role (reboot may be required) |

Paste-ready (elevated PowerShell on the Nest):

```powershell
# Pubkey from Settings → Security, or: hatchery remoting-identity show hatchery
$pub = "ssh-ed25519 AAAA... hatchery"

.\authorize-hatchery-nest-ssh-windows.ps1 -PublicKey $pub
.\enable-hyperv-windows.ps1
# Restart if the Hyper-V script warns that a reboot is needed
```

Or from a file your MDM / internal tooling dropped:

```powershell
.\authorize-hatchery-nest-ssh-windows.ps1 -PublicKeyPath C:\ProgramData\hatchery\hatchery.pub
.\enable-hyperv-windows.ps1
```

Internal automation can push the same pubkey into `authorized_keys` without these scripts; the contract is identical: Nest OpenSSH trusts the Controller remoting identity public key, and Hyper-V is available for Nest VM ops.

For Linux / macOS Nests, install `sshd`, append the same pubkey to the Nest user’s `~/.ssh/authorized_keys`, and open TCP 22. Library helpers: [`enable-ssh-linux.sh`](https://github.com/dustinestes/Hatchery-Library/blob/main/scripts/linux/enable-ssh-linux.sh) / [`enable-ssh-macos.sh`](https://github.com/dustinestes/Hatchery-Library/blob/main/scripts/macos/enable-ssh-macos.sh) (enable sshd only; still add the Hatchery pubkey yourself).

<br>

## Register and test

1. **Nests → Connections** → add Nest
2. `location=remote`, host / user / port
3. Bind **Remoting identity** (`remoting_identity_id`) - the identity whose pubkey you authorized
4. Provider type: `hyperv` (or `libvirt` / `utm` when that Nest type applies)
5. **Test Nest connection**

CLI inspect (when registered):

```bash
uv run hatchery nest list
uv run hatchery --json nest show <nest-id>
```

Connectivity stages (endpoint TCP vs authenticated transport) are documented in [Nest transport - Connectivity check](nest-transport.md#connectivity-check).

<br>

## Known hosts

Nest SSH `known_hosts` policy on the Nest connection: `default` | `accept-new` | `skip` (see Nest transport). Lab Nests often use `accept-new` once; production should pin host keys under `default` after the first trust.

<br>

## Identity expiry

Optional certificate / expiry alerts live on the remoting identity (Security alert tiers). See [Nest key expiry](nest-key-expiry.md).

<br>

## Troubleshooting

| Symptom | Check |
|---|---|
| Test fails with **endpoint** | Nest host/IP, route, firewall TCP 22 (or custom port) |
| Test fails with **transport** | Pubkey on Nest matches the bound remoting identity; SSH user; Windows admin → `administrators_authorized_keys`; `sshd` running |
| `ssh: command not found` on Controller | Install OpenSSH **client** on the Controller OS |
| Permission denied (publickey) | Wrong identity bound; pubkey not installed; wrong Nest user |
| Hyper-V cmdlets missing later | Run `enable-hyperv-windows.ps1` and reboot; confirm Nest SKU supports Hyper-V |
| WinRM instead of SSH | Set Nest transport to WinRM when OpenSSH cannot be used ([Nest transport - WinRM](nest-transport.md#winrm-fallback)) |

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
