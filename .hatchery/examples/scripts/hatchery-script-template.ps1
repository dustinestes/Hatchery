# ============================================================
# Hatchery Automation Script Template
# ============================================================
# Copy this file to your Hatchery automation/scripts/ directory
# and declare it in your Clutch file under a VM's automations list.
#
# How Hatchery runs this script:
#   - Injects Write-HatchEvent so it is always available (after param() if present)
#   - Connects to the guest over WinRM and executes the script content
#   - Captures all output (stdout + stderr) and stores it per-script
#   - Reads the exit code when the script finishes:
#       0  = success → next script runs (or VM is marked fledged)
#       >0 = failure → provisioning halts, remaining scripts are skipped,
#                      VM is marked failed (retryable from the Nests panel)
#
# Conventions:
#   - Use Write-HatchEvent for progress lines — they appear in the live feed
#   - Use $ErrorActionPreference = "Stop" so unhandled errors become fatal
#   - Wrap the main body in try/catch and exit with a non-zero code on failure
#   - Keep each script focused on one concern — compose behaviour via the
#     automations list in your Clutch file, not by chaining logic inside scripts
#
# Write-HatchEvent signature (injected by Hatchery — do not define it yourself):

#
#   Write-HatchEvent -Message "text" [-Tier INFO|WARN|ERROR] [-Component "label"]
#
#   Tier defaults to INFO. Use WARN for non-fatal advisories, ERROR for failures
#   that you catch but still want flagged (exit code drives the actual outcome).
#   Component is an optional sub-label (e.g. "Chocolatey", "Registry") shown
#   in the live feed to group related lines.
# ============================================================

# ── Parameters (optional) ─────────────────────────────────────────────────────
# Declare script parameters here if your script needs configurable inputs.
# Hatchery introspects this block to render input fields in the Clutch builder
# UI. Values can also be set manually in your Clutch file under the script's
# "parameters" key.
#
# Parameter attributes Hatchery reads:
#   Mandatory    — field is marked required in the UI
#   HelpMessage  — shown as a tooltip on the help icon next to the field
#
# Remove this entire param() block if your script takes no inputs.
<#
param(
    [Parameter(Mandatory = $true, HelpMessage = "Describe what this parameter does.")]
    [string]$ExampleParam,

    [Parameter(Mandatory = $false, HelpMessage = "An optional parameter with a default value.")]
    [string]$OptionalParam = "default-value",

    [Parameter(Mandatory = $false, HelpMessage = "A boolean flag, e.g. to enable verbose mode.")]
    [bool]$EnableFeature = $false
)
#>

$ErrorActionPreference = "Stop"

# ── Main ──────────────────────────────────────────────────────────────────────

try {
    Write-HatchEvent "Script started"

    # --- Your work goes here ---
    #
    # Example: install a Chocolatey package
    #   Write-HatchEvent "Installing git" -Component "Chocolatey"
    #   choco install git -y --no-progress
    #
    # Example: set a registry value
    #   Write-HatchEvent "Writing registry key" -Component "Registry"
    #   Set-ItemProperty -Path "HKLM:\SOFTWARE\MyApp" -Name "Setting" -Value 1
    #
    # Example: non-fatal advisory
    #   Write-HatchEvent "Key not found, using default" -Tier WARN -Component "Registry"
    #
    # Any exception thrown inside this try block will be caught below,
    # written to the error stream, and exit with code 1 so Hatchery marks
    # the script failed.
    #
    # Exit codes:
    #   0        = success — Hatchery continues to the next script
    #   non-zero = failure — Hatchery halts provisioning and marks the VM
    #              failed; remaining scripts are skipped. The actual code
    #              value is stored and displayed in the Nests panel so you
    #              can use specific codes (e.g. exit 2, exit 99) for your
    #              own diagnostic purposes.

    Write-HatchEvent "Script completed successfully"
    exit 0

} catch {
    Write-HatchEvent "Script failed: $_" -Tier ERROR
    exit 1
}
