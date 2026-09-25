# ============================================================
# install-virtio-drivers.ps1
# Install VirtIO drivers and QEMU guest agent from the attached
# virtio-win ISO (secondary CD-ROM attached at hatch time).
#
# Prerequisites:
#   1. Select a VirtIO ISO in the Clutch (VirtIO Drivers field)
#   2. Hatch - Hatchery attaches it as a CD-ROM
#   3. After OS install, run this script over WinRM
#
# Copy to automation/scripts/ and declare in a Clutch:
#
#   automations:
#     - name: install-virtio-drivers.ps1
#       parameters:
#         DriveLetter: "E"
#         # or leave DriveLetter empty and set IsoLabel:
#         IsoLabel: "virtio-win"
#
# Driver install is optional - guests on IDE/e1000 do not need this.
# Prefer attaching VirtIO at hatch so Windows Setup can load
# viostor during install; this script covers post-install tools.
# ============================================================

param(
    [Parameter(Mandatory = $false, HelpMessage = "Drive letter of the mounted VirtIO ISO (e.g. 'E'). Takes precedence over IsoLabel.")]
    [string]$DriveLetter = "",

    [Parameter(Mandatory = $false, HelpMessage = "Volume label of the VirtIO ISO when DriveLetter is empty. Default: virtio-win.")]
    [string]$IsoLabel = "virtio-win"
)

$ErrorActionPreference = "Stop"

function Resolve-VirtioRoot {
    param(
        [string]$Letter,
        [string]$Label
    )

    if ($Letter) {
        $letterOnly = $Letter.TrimEnd(":").Trim()
        $root = "${letterOnly}:\"
        if (-not (Test-Path -LiteralPath $root)) {
            throw "Drive '$root' not found. Confirm the VirtIO ISO is attached and mounted."
        }
        return (Resolve-Path -LiteralPath $root).Path
    }

    $disk = Get-CimInstance -ClassName Win32_LogicalDisk -ErrorAction SilentlyContinue |
        Where-Object { $_.VolumeName -and ($_.VolumeName -ieq $Label) } |
        Select-Object -First 1
    if (-not $disk -or -not $disk.DeviceID) {
        throw "No volume with label '$Label' found. Pass DriveLetter or confirm the VirtIO ISO is attached."
    }
    $root = "$($disk.DeviceID)\"
    if (-not (Test-Path -LiteralPath $root)) {
        throw "Resolved VirtIO volume '$root' is not accessible."
    }
    return (Resolve-Path -LiteralPath $root).Path
}

try {
    $isoRoot = Resolve-VirtioRoot -Letter $DriveLetter -Label $IsoLabel
    Write-HatchEvent "VirtIO ISO root: $isoRoot" -Component "VirtIO"

    # Prefer the all-in-one guest tools MSI when present (newer virtio-win ISOs).
    $guestTools = @(
        Join-Path $isoRoot "virtio-win-gt-x64.msi"
        Join-Path $isoRoot "virtio-win-gt-x86.msi"
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

    if ($guestTools) {
        Write-HatchEvent "Installing guest tools MSI: $guestTools" -Component "VirtIO"
        $p = Start-Process -FilePath "msiexec.exe" `
            -ArgumentList "/i `"$guestTools`" /qn /norestart" `
            -Wait -PassThru
        if ($p.ExitCode -notin 0, 3010) {
            throw "msiexec failed for guest tools with exit code $($p.ExitCode)"
        }
        Write-HatchEvent "Guest tools MSI installed (exit $($p.ExitCode))" -Component "VirtIO"
    } else {
        Write-HatchEvent "Guest tools MSI not found - installing INF drivers via pnputil" `
            -Level WARN -Component "VirtIO"

        Write-HatchEvent "Running pnputil /add-driver on $isoRoot" -Component "VirtIO"
        $pnpu = Start-Process -FilePath "pnputil.exe" `
            -ArgumentList "/add-driver `"$isoRoot\*`" /subdirs /install" `
            -Wait -PassThru -NoNewWindow
        # pnputil returns 0 on success; non-zero may still mean partial success
        Write-HatchEvent "pnputil finished with exit code $($pnpu.ExitCode)" -Component "VirtIO"

        $gaCandidates = @(
            Join-Path $isoRoot "guest-agent\qemu-ga-x86_64.msi"
            Join-Path $isoRoot "guest-agent\qemu-ga-i386.msi"
        ) | Where-Object { Test-Path -LiteralPath $_ }

        $ga = $gaCandidates | Select-Object -First 1
        if ($ga) {
            Write-HatchEvent "Installing QEMU guest agent: $ga" -Component "VirtIO"
            $p = Start-Process -FilePath "msiexec.exe" `
                -ArgumentList "/i `"$ga`" /qn /norestart" `
                -Wait -PassThru
            if ($p.ExitCode -notin 0, 3010) {
                throw "msiexec failed for guest agent with exit code $($p.ExitCode)"
            }
            Write-HatchEvent "Guest agent installed (exit $($p.ExitCode))" -Component "VirtIO"
        } else {
            Write-HatchEvent "QEMU guest agent MSI not found under guest-agent\" `
                -Level WARN -Component "VirtIO"
        }
    }

    Write-HatchEvent "VirtIO driver installation complete"
    exit 0

} catch {
    Write-HatchEvent "Script failed: $_" -Level ERROR
    exit 1
}
