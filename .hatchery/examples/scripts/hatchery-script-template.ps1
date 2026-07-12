# ============================================================
# Hatchery Automation Script Template
# ============================================================
# Copy this file to your Hatchery automation/scripts/ directory
# and declare it in your Clutch file under a VM's automations list.
#
# How Hatchery runs this script:
#   - Connects to the guest over WinRM and executes the script content
#   - Captures all output (stdout + stderr) and displays it in the Nests panel
#   - Reads the exit code when the script finishes:
#       0  = success → next script runs (or VM is marked fledged)
#       >0 = failure → provisioning halts, remaining scripts are skipped,
#                      VM is marked failed (retryable from the Nests panel)
#
# Conventions:
#   - Use Write-Output for progress lines you want visible in the Nests panel
#   - Use $ErrorActionPreference = "Stop" so unhandled errors become fatal
#   - Wrap the main body in try/catch and exit with a non-zero code on failure
#   - Keep each script focused on one concern — compose behaviour via the
#     automations list in your Clutch file, not by chaining logic inside scripts
# ============================================================

# ── Parameters (optional) ─────────────────────────────────────────────────────
# Declare script parameters here if your script needs configurable inputs.
# Hatchery (issue #113) will introspect this block to render input fields in
# the Clutch builder UI. Until that feature lands, values can be hard-coded or
# set manually in your Clutch file under the script's "parameters" key.
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

function Write-Step {
    param([string]$Message)
    # Write-Output goes to the success stream (stream 1) and is reliably
    # captured by Hatchery across all WinRM configurations. Avoid Write-Host
    # for automation scripts — it targets the information stream (stream 6)
    # and may not be captured depending on the Windows version and WinRM setup.
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] $Message"
}

# ── Main ──────────────────────────────────────────────────────────────────────

try {
    Write-Step "Script started"

    # --- Your work goes here ---
    #
    # Example: install a Chocolatey package
    #   choco install git -y --no-progress
    #
    # Example: set a registry value
    #   Set-ItemProperty -Path "HKLM:\SOFTWARE\MyApp" -Name "Setting" -Value 1
    #
    # Example: copy a file
    #   Copy-Item -Path "C:\Source\config.json" -Destination "C:\App\config.json"
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

    Write-Step "Script completed successfully"
    exit 0

} catch {
    Write-Error "[ERROR] $_"
    exit 1
}
