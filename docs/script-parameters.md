<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Script parameters</h1>
<br clear="both">

Typed Clutch script parameters: what Hatchery **discovers**, how the form and early gates behave, and how values are encoded at guest invoke. For writing scripts and Clutch wiring, see [Automation Scripts](automations.md). Decision record: [ADR-0034](adr/0034-script-param-discover-dont-invent.md) / [#571](https://github.com/dustinestes/Hatchery/issues/571).

<br>

## Contents

- [Contents](#contents)
- [Discover, don't invent](#discover-dont-invent)
- [Kinds (types)](#kinds-types)
- [Constraints](#constraints)
- [UI, save, and hatch gates](#ui-save-and-hatch-gates)
- [YAML and invoke encoding](#yaml-and-invoke-encoding)
- [Controller `pwsh`](#controller-pwsh)
- [Not supported yet](#not-supported-yet)
- [Test fixture](#test-fixture)
- [Related](#related)

---

<br>

## Discover, don't invent

Clutch Build/Edit **discovers** parameter types and constraints from the script itself (kind adapters in [`lib/script_params.py`](../lib/script_params.py)), then adapts form fields and early validation to those specs only. Hatchery does **not** invent enums, lengths, or types the script did not declare.

| Script kind | Reader (Controller) | Status |
|---|---|---|
| PowerShell (`.ps1`) | `pwsh` `Get-Command` introspection | Landed |
| Shell (`.sh` / `.bash`) | TBD adapter | Planned (same Clutch UI) |

When metadata is available, invalid values (wrong type, outside `ValidateSet`, outside `ValidateLength`, missing mandatory) **block Clutch save and hatch** before any guest runs. When metadata is empty (no reader, no `pwsh`, or no `param()` block), the form shows no typed fields and there is no strict param gate - configure `parameters` in YAML manually if needed.

Guest param-binding failure remains a last-resort backstop (must not look like exit 0 success). Prefer failing in the form / preflight.

<br>

---

<br>

## Kinds (types)

| `kind` | PowerShell types that map to it | Clutch UI | YAML / form save | Invoke encode (`.ps1`) |
|---|---|---|---|---|
| `string` | Default for undeclared / other types (e.g. `[string]`) | Text (or select when `ValidateSet`) | string | `-Name 'quoted'` |
| `bool` | `[bool]` / `Boolean` | Checkbox | `true` / `false` | `-Name $true` / `$false` |
| `switch` | `[switch]` / `SwitchParameter` | Checkbox | bool | present → `-Name`; false → `-Name:$false` |
| `int` | `int` / `int16` / `int32` / `int64` / `long` / `short` / `sbyte` / `byte` / `uint16` / `uint32` / `uint64` | Number (step 1) | number | unquoted `-Name 3` |
| `float` | `double`, `single`, `float`, `decimal` | Number | number | unquoted |

Signed integer types allow negatives. Unsigned / `byte` types set `min_value` (and `max_value` for `byte` / `uint16`) from the CLR type so the form and early gates reject out-of-range values (for example `uint` cannot be negative). `ValidateRange` is not discovered yet.

Common PowerShell cmdlet parameters (`Verbose`, `Debug`, `ErrorAction`, `WarningAction`, `InformationAction`, `ProgressAction`, `WhatIf`, `Confirm`, and related `*Variable` / `OutBuffer` parameters) are filtered out and never shown in the Clutch UI.

<br>

---

<br>

## Constraints

| Constraint | Source attribute | Effect |
|---|---|---|
| **Mandatory** | `[Parameter(Mandatory = $true)]` | Required in UI; block save/hatch when missing and no default |
| **Help** | `HelpMessage` | Tooltip / accessible description |
| **Default** | script default | Pre-fills UI; mandatory + default → empty is allowed |
| **ValidateSet** | `[ValidateSet(...)]` | Select options; reject values outside the set |
| **ValidateLength** | `[ValidateLength(min, max)]` | `min_length` / `max_length` on **string** values |

Legacy stringly YAML for bools still coerces when metadata exists: `true` / `1` / `yes` / `on` and `false` / `0` / `no` / `off` (case-insensitive). Tokens that cannot coerce (e.g. `"not-a-bool"`) fail early.

<br>

---

<br>

## UI, save, and hatch gates

When introspection returns specs:

1. **Clutch Build/Edit** renders typed controls and inline validation as the operator edits
2. Script **defaults** are prefilled into the fields when the Clutch has no saved value yet (operators edit from the default; the details popover also lists Default so they can restore it)
3. **Save** (Build/Edit) rejects Clutches whose script params fail type / validation / mandatory checks
4. **Hatch** (UI + CLI) runs the same shared validate before session create

The details popover **Type** is the PowerShell / CLR type from `[Type]$Name` (for example `Double`, `SwitchParameter`, `UInt32`). **Control** is how Hatchery presents that type in the form (Number, Checkbox, Text, Dropdown).

Hand-edited YAML is subject to the same rules at hatch (and at save if edited in-app).

<br>

---

<br>

## YAML and invoke encoding

Prefer YAML natives that match the script:

```yaml
parameters:
  IncludeManagementTools: true   # bool → -IncludeManagementTools $true
  RetryCount: 2                  # int → -RetryCount 2
  Environment: lab               # ValidateSet string
```

Legacy stringly `"true"` / `"True"` still coerce when specs exist, then encode as `$true` (not a quoted `'True'`). That is the lab failure mode [#571](https://github.com/dustinestes/Hatchery/issues/571) fixed for `[bool]$IncludeManagementTools`.

For multi-value **string** inputs that the script parses itself (`RdpUsers`, `PackageNames`), pass a comma-separated list - there is no first-class array kind yet.

<br>

---

<br>

## Controller `pwsh`

`pwsh` is **optional** on the Controller for PowerShell scripts. Install it to enable typed fields and early gates:

```bash
# Install the Microsoft package feed, then:
sudo apt-get install -y powershell
```

Full installation instructions: [Installing PowerShell on Linux](https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell-on-linux).

After installation, the Requirements check in Settings shows `pwsh` as satisfied and introspection activates automatically. Controllers without `pwsh` keep the weaker path (manual YAML params, no typed fields / no strict param gate).

<br>

---

<br>

## Not supported yet

| Area | Status |
|---|---|
| Shell (`.sh` / `.bash`) param discovery + encode | Planned adapter; same Clutch UI |
| PowerShell **parameter sets** (`ParameterSetName`) | Considered; unsupported (see below) |
| `ValidatePattern`, `ValidateRange`, `ValidateScript`, `ValidateNotNull`, … | Not discovered |
| First-class array / `[string[]]` kind | Falls through to `string` |
| Hatchery-invented enums or lengths | Explicitly out of scope (discover only) |

### PowerShell parameter sets

PowerShell `param()` blocks may assign parameters to named **parameter sets** (`[Parameter(ParameterSetName = '...')]`) so a script exposes mutually exclusive calling shapes. Hatchery **does not** model sets today.

**Why deferred:** supporting them cleanly needs more than flattening attributes. The Clutch form would almost certainly need an explicit **parameter-set selector** (dropdown above the fields) that shows only the params for the chosen set, remaps mandatory / defaults per set, and encodes invoke args for that set alone. Until Library scripts need that UX, the cost outweighs the benefit.

**What happens now:** introspection returns every declared parameter in one flat list. Set membership is ignored. Scripts that rely on sets can look wrong in the form (for example two set-exclusive mandatory params both appear required) and may fail at guest bind if the operator fills an incompatible combination.

**Author guidance:** for Clutch-bound Scripts, prefer a single flat `param()` (optional params + defaults / `ValidateSet`) rather than multiple parameter sets. If a script already uses sets, treat Hatchery params as a best-effort flat map and validate carefully on the guest.

<br>

---

<br>

## Test fixture

Hatchery-Library ships [`test-param-smoke-windows.ps1`](https://github.com/dustinestes/Hatchery-Library/blob/main/tests/scripts/windows/test-param-smoke-windows.ps1) under `tests/scripts/` (not production `scripts/`). Enable the opt-in **Test Scripts** Library binding (`tests/scripts/*`, [#573](https://github.com/dustinestes/Hatchery/issues/573)), pull, then add the script in Clutch Build to exercise every landed kind and constraint. On the guest it dumps bound values via `Write-HatchEvent`, stdout, and a file under `HATCHERY_LOGS`.

<br>

---

<br>

## Related

- [Automation Scripts](automations.md) - writing scripts, `Write-HatchEvent`, Clutch `automations` list
- [ADR-0034](adr/0034-script-param-discover-dont-invent.md) - discover / adapter decision
- [Library](library.md) - Test Scripts binding
- [Answer Files](answer-files.md) - install-time parameters (frontmatter, not PowerShell introspection)

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
