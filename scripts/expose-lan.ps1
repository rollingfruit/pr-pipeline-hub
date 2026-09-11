[CmdletBinding()]
param(
    [ValidateSet("install", "remove", "status")]
    [string]$Operation = "status",
    [string]$Distro = "Ubuntu-24.04",
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
$ruleName = "PR Pipeline Hub TCP $Port"

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-WslAddress {
    $addresses = (& wsl.exe -d $Distro -- hostname -I).Trim() -split "\s+"
    $address = $addresses | Where-Object { $_ -match "^\d+\.\d+\.\d+\.\d+$" -and $_ -notlike "172.17.*" } | Select-Object -First 1
    if (-not $address) { throw "Unable to resolve the $Distro IPv4 address" }
    return $address
}

function Get-LanAddresses {
    Get-NetIPConfiguration |
        Where-Object { $_.NetAdapter.Status -eq "Up" -and $_.IPv4Address -and $_.IPv4DefaultGateway } |
        ForEach-Object { $_.IPv4Address.IPAddress }
}

switch ($Operation) {
    "install" {
        if (-not (Test-Administrator)) { throw "Run this script from an elevated PowerShell window" }
        $wslAddress = Get-WslAddress
        & netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$Port | Out-Null
        & netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$Port connectaddress=$wslAddress connectport=$Port
        Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Domain,Private | Out-Null
        Write-Output "Forwarding 0.0.0.0:$Port to ${wslAddress}:$Port"
        Get-LanAddresses | ForEach-Object { Write-Output "LAN URL: http://${_}:$Port" }
    }
    "remove" {
        if (-not (Test-Administrator)) { throw "Run this script from an elevated PowerShell window" }
        & netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$Port
        Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    }
    "status" {
        & netsh interface portproxy show v4tov4
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object LocalAddress, LocalPort, OwningProcess
        Get-LanAddresses | ForEach-Object { Write-Output "Candidate LAN URL: http://${_}:$Port" }
    }
}

