# ============================================================
# remove-appx.ps1
# Remove provisioned / installed AppX packages from a Windows guest.
#
# Copy to automation/scripts/ and declare in a Clutch:
#
#   automations:
#     - name: remove-appx.ps1
#       parameters:
#         PackageNames: "Microsoft.BingNews,Microsoft.XboxApp"
#         RemoveAll: "false"
#
# PackageNames is a comma-separated list of AppX Name values
# (Get-AppxPackage | Select Name). Matching is by -like '*Name*'.
#
# When RemoveAll is true, every non-framework AppX package for all
# users is removed and PackageNames is ignored.
#
# Use with care: RemoveAll can strip Store and inbox apps operators
# still expect. Prefer an explicit PackageNames list for lab images.
# ============================================================

param(
    [Parameter(Mandatory = $false, HelpMessage = "Comma-separated AppX package Name values to remove (substring match). Ignored when RemoveAll is true.")]
    [string]$PackageNames = "",

    [Parameter(Mandatory = $false, HelpMessage = "When true, remove all non-framework AppX packages for all users and ignore PackageNames.")]
    [bool]$RemoveAll = $false
)

$ErrorActionPreference = "Stop"

function Remove-AppxByPackage {
    param([Parameter(Mandatory = $true)] $Package)

    $full = $Package.PackageFullName
    Write-HatchEvent "Removing AppX '$full'" -Component "AppX"
    try {
        Remove-AppxPackage -Package $full -AllUsers -ErrorAction Stop
    } catch {
        # Fall back to current-user removal when -AllUsers is unavailable
        Remove-AppxPackage -Package $full -ErrorAction Stop
    }
}

try {
    if ($RemoveAll) {
        Write-HatchEvent "RemoveAll=true - removing all non-framework AppX packages" -Component "AppX"
        $packages = Get-AppxPackage -AllUsers -ErrorAction SilentlyContinue |
            Where-Object { -not $_.IsFramework }
        if (-not $packages) {
            $packages = Get-AppxPackage -ErrorAction SilentlyContinue |
                Where-Object { -not $_.IsFramework }
        }
        $count = 0
        foreach ($pkg in @($packages)) {
            Remove-AppxByPackage -Package $pkg
            $count++
        }
        Write-HatchEvent "Removed $count AppX package(s)" -Component "AppX"
        exit 0
    }

    $names = @($PackageNames -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if ($names.Count -eq 0) {
        Write-HatchEvent "No PackageNames provided and RemoveAll is false - nothing to do" `
            -Level WARN -Component "AppX"
        exit 0
    }

    $all = @(Get-AppxPackage -AllUsers -ErrorAction SilentlyContinue)
    if ($all.Count -eq 0) {
        $all = @(Get-AppxPackage -ErrorAction SilentlyContinue)
    }

    $removed = 0
    foreach ($name in $names) {
        $matches = @($all | Where-Object { $_.Name -like "*$name*" })
        if ($matches.Count -eq 0) {
            Write-HatchEvent "No AppX package matched '$name'" -Level WARN -Component "AppX"
            continue
        }
        foreach ($pkg in $matches) {
            Remove-AppxByPackage -Package $pkg
            $removed++
        }
    }

    Write-HatchEvent "Removed $removed AppX package(s)" -Component "AppX"
    exit 0

} catch {
    Write-HatchEvent "Script failed: $_" -Level ERROR
    exit 1
}
