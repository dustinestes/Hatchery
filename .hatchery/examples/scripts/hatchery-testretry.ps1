# ============================================================
# hatchery-testretry.ps1
# End-to-end test for Hatchery's retry mechanism.
#
# First run:  writes a flag to C:\Program Files\Hatchery\temp\
#             then exits 1 so Hatchery marks the VM failed.
# Retry run:  finds the flag, deletes it, exits 0 so Hatchery
#             marks the script succeeded and continues automation.
#
# Usage in a Clutch:
#   automations:
#     - hatchery-testretry.ps1
#     - <next script>   # only reached on the retry run
# ============================================================

$ErrorActionPreference = "Stop"
$FlagFile = "C:\Program Files\Hatchery\temp\hatchery-testretry-ran"

try {
    if (Test-Path $FlagFile) {
        Write-HatchEvent "Retry flag found -- this is the retry run" -Component "hatchery-testretry"
        Remove-Item -Path $FlagFile -Force
        Write-HatchEvent "Flag removed -- retry succeeded" -Component "hatchery-testretry"
        exit 0
    }

    Write-HatchEvent "First run -- writing retry flag and failing intentionally" -Component "hatchery-testretry"
    $null = New-Item -Path $FlagFile -ItemType File -Force
    Write-HatchEvent "Flag written to: $FlagFile" -Component "hatchery-testretry"
    Write-HatchEvent "Exiting with code 1 -- use Hatchery retry to continue" -Level WARN -Component "hatchery-testretry"
    exit 1

} catch {
    Write-HatchEvent "Unexpected error: $_" -Level ERROR -Component "hatchery-testretry"
    exit 1
}
