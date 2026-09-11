[CmdletBinding()]
param(
    [ValidateSet("start", "restart", "stop", "status", "logs")]
    [string]$Operation = "start"
)

$ErrorActionPreference = "Stop"
$settings = Get-ItemProperty -LiteralPath "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
$proxy = ""
if ($settings.ProxyEnable -eq 1 -and $settings.ProxyServer) {
    $proxy = [string]$settings.ProxyServer
    if ($proxy -notmatch "://") { $proxy = "http://$proxy" }
}

$script = "/mnt/d/code/welink-micro/pr-pipeline-hub/scripts/quick-tunnel.sh"
if ($proxy) {
    & wsl.exe -- env "PIPELINE_WINDOWS_PROXY=$proxy" bash $script $Operation
} else {
    & wsl.exe -- bash $script $Operation
}
if ($LASTEXITCODE -ne 0) { throw "Quick Tunnel $Operation failed" }
