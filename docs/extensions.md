# Controller extensions

How the free Hatchery Controller optionally loads the commercial **Enterprise** package. Product boundary: [ADR-0042](adr/0042-open-core-public-and-enterprise-tier.md), load shape: [ADR-0043](adr/0043-controller-extension-load.md). Edition how-to: [`docs/enterprise/`](enterprise/).

<br>

## What loads

If the `hatchery-enterprise` Python package is installed, the Controller calls:

```text
hatchery_enterprise.register(api)
```

Absent package → free entitlements only (`max_nests=1`, no feature packs). Public CI never requires the private package.

Entitlement packs and capacity for paying installs come from a **signed license** delivered with the commercial package (portal work tracked in Hatchery-Enterprise). Free Hatchery does not read commercial env knobs or license files.

<br>

## Code map

| Piece | Role |
|---|---|
| [`lib/extensions/`](../lib/extensions/) | Join point only (not paid feature implementations) |
| `Entitlements` | `max_nests` + `features` set |
| `ExtensionApi` | `set_entitlements`, `register_cli`, `register_flask`, `register_validator` |
| `load_extensions()` | Try-import + idempotent register |

Paid Nest Agent, multi-Nest, and related code live in the private `hatchery-enterprise` package and attach through this API.
