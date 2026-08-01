# ============================================================
# hatchery-cleanup.ps1
# Removes the Hatchery guest directory and all its contents.
#
# Add this as the LAST script in your Clutch's automations list
# if you want to remove all Hatchery artifacts from the guest
# after provisioning completes. Once removed, the Hatchery event
# log becomes the sole audit record.
#
# If omitted, C:\Program Files\Hatchery\ remains on the guest
# as a local audit record containing:
#   logs\hatchery-setup.log   — first-boot setup steps
#   logs\<script-name>.log    — per-script automation events
#
#   automations:
#     - name: hatchery-cleanup.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$HatcheryDir = "C:\Program Files\Hatchery"

try {
    if (Test-Path $HatcheryDir) {
        Write-HatchEvent "Removing Hatchery guest directory: $HatcheryDir"
        Remove-Item -Path $HatcheryDir -Recurse -Force
        Write-HatchEvent "Hatchery guest directory removed"
    } else {
        Write-HatchEvent "Hatchery guest directory not found -- nothing to remove" -Level WARN
    }
    exit 0
} catch {
    Write-HatchEvent "Cleanup failed: $_" -Level ERROR
    exit 1
}
