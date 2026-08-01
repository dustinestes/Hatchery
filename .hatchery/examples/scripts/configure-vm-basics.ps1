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

try {
    # ── Timezone ──────────────────────────────────────────────────────────────
    Write-HatchEvent "Setting timezone to '$TimeZone'" -Component "Timezone"
    Set-TimeZone -Id $TimeZone
    Write-HatchEvent "Timezone set" -Component "Timezone"

    # ── Rename ────────────────────────────────────────────────────────────────
    $current = $env:COMPUTERNAME
    if ($current -eq $ComputerName) {
        Write-HatchEvent "Computer is already named '$ComputerName' — skipping rename" -Level WARN -Component "Rename"
    } else {
        Write-HatchEvent "Renaming computer from '$current' to '$ComputerName'" -Component "Rename"
        Rename-Computer -NewName $ComputerName -Force
        Write-HatchEvent "Rename staged — reboot required to take effect" -Component "Rename"
    }

    Write-HatchEvent "Basic configuration complete"
    exit 0

} catch {
    Write-HatchEvent "Script failed: $_" -Level ERROR
    exit 1
}
