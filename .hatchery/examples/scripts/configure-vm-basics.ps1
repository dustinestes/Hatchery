# ============================================================
# configure-vm-basics.ps1
# Basic VM configuration — rename and timezone.
#
# Declare this script in your Clutch with reboot_after: true so
# the rename takes effect before subsequent scripts run:
#
#   automations:
#     - name: configure-vm-basics.ps1
#       reboot_after: true
#       parameters:
#         ComputerName: dc01
#         TimeZone: "Central Standard Time"
#
# To list available timezone IDs on any Windows machine:
#   Get-TimeZone -ListAvailable | Select-Object Id
# ============================================================

param(
    [Parameter(Mandatory = $true, HelpMessage = "New name for this computer. Must be 15 characters or fewer.")]
    [ValidateLength(1, 15)]
    [string]$ComputerName,

    [Parameter(Mandatory = $false, HelpMessage = "Windows timezone ID, e.g. 'Central Standard Time'. Defaults to UTC if not set.")]
    [string]$TimeZone = "UTC"
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] $Message"
}

try {
    # ── Timezone ──────────────────────────────────────────────────────────────
    Write-Step "Setting timezone to '$TimeZone'"
    Set-TimeZone -Id $TimeZone
    Write-Step "Timezone set"

    # ── Rename ────────────────────────────────────────────────────────────────
    $current = $env:COMPUTERNAME
    if ($current -eq $ComputerName) {
        Write-Step "Computer is already named '$ComputerName' — skipping rename"
    } else {
        Write-Step "Renaming computer from '$current' to '$ComputerName'"
        Rename-Computer -NewName $ComputerName -Force
        Write-Step "Rename staged — reboot required to take effect"
    }

    Write-Step "Basic configuration complete"
    exit 0

} catch {
    Write-Error "[ERROR] $_"
    exit 1
}
