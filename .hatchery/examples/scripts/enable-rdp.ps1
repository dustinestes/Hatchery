# ============================================================
# enable-rdp.ps1
# Enable Remote Desktop and grant access to users/groups.
#
# Copy to automation/scripts/ and declare in a Clutch:
#
#   automations:
#     - name: enable-rdp.ps1
#       parameters:
#         RdpUsers: "DOMAIN\\ops,labuser"
#
# RdpUsers is a comma-separated list of local or domain accounts
# (or groups) added to the Remote Desktop Users group. Use this for
# non-admin operators; leave empty to only enable RDP. Members of
# Administrators already have Remote Desktop logon rights by default
# and do not need (and should not be added to) Remote Desktop Users.
# ============================================================

param(
    [Parameter(Mandatory = $false, HelpMessage = "Comma-separated non-admin users/groups to add to Remote Desktop Users (e.g. 'DOMAIN\\ops,labuser'). Administrators already have RDP access.")]
    [string]$RdpUsers = ""
)

$ErrorActionPreference = "Stop"

try {
    Write-HatchEvent "Enabling Remote Desktop" -Component "RDP"

    # Allow RDP connections (0 = enabled)
    Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server" `
        -Name "fDenyTSConnections" -Value 0 -Type DWord

    # Prefer NLA when available (1 = require Network Level Authentication)
    Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp" `
        -Name "UserAuthentication" -Value 1 -Type DWord

    $firewall = Get-NetFirewallRule -DisplayGroup "Remote Desktop" -ErrorAction SilentlyContinue
    if ($firewall) {
        Enable-NetFirewallRule -DisplayGroup "Remote Desktop"
        Write-HatchEvent "Firewall rule group 'Remote Desktop' enabled" -Component "RDP"
    } else {
        Write-HatchEvent "Remote Desktop firewall group not found; skipping firewall enable" `
            -Level WARN -Component "RDP"
    }

    $names = @($RdpUsers -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    foreach ($name in $names) {
        Write-HatchEvent "Adding '$name' to Remote Desktop Users" -Component "RDP"
        # net localgroup tolerates domain\user and BUILTIN\Group forms
        $result = & net.exe localgroup "Remote Desktop Users" $name /add 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-HatchEvent "Added '$name'" -Component "RDP"
        } elseif ("$result" -match "already a member") {
            Write-HatchEvent "'$name' is already a member - skipping" -Level WARN -Component "RDP"
        } else {
            throw "Failed to add '$name' to Remote Desktop Users: $result"
        }
    }

    Write-HatchEvent "Remote Desktop enabled"
    exit 0

} catch {
    Write-HatchEvent "Script failed: $_" -Level ERROR
    exit 1
}
