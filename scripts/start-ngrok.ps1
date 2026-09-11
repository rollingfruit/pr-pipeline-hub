[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "restart", "stop", "status", "logs", "auth", "auth-clipboard")]
    [string]$Operation = "start",
    [string]$Authtoken
)

$ErrorActionPreference = "Stop"
$root = "/mnt/d/code/welink-micro/pr-pipeline-hub"

if ($Operation -eq "auth") {
    if (-not $Authtoken) { throw "Use -Authtoken with the token from https://dashboard.ngrok.com/get-started/your-authtoken" }
    & wsl.exe -d Ubuntu-24.04 -- "$root/.runtime/bin/ngrok" config add-authtoken $Authtoken
} elseif ($Operation -eq "auth-clipboard") {
    $clipboard = (Get-Clipboard -Raw).Trim()
    if ($clipboard -match "ngrok\s+config\s+add-authtoken\s+([^\s]+)") {
        $Authtoken = $Matches[1]
    } elseif ($clipboard -notmatch "\s" -and $clipboard.Length -ge 30) {
        $Authtoken = $clipboard
    } else {
        throw "Clipboard does not contain an ngrok Authtoken or add-authtoken command"
    }

    $temporaryToken = Join-Path (Split-Path $PSScriptRoot -Parent) ".runtime\ngrok-auth.tmp"
    try {
        [IO.File]::WriteAllText($temporaryToken, $Authtoken, [Text.UTF8Encoding]::new($false))
        & wsl.exe -d Ubuntu-24.04 -- bash -lc 'token=$(cat /mnt/d/code/welink-micro/pr-pipeline-hub/.runtime/ngrok-auth.tmp); /mnt/d/code/welink-micro/pr-pipeline-hub/.runtime/bin/ngrok config add-authtoken "$token" >/dev/null; /mnt/d/code/welink-micro/pr-pipeline-hub/.runtime/bin/ngrok config check'
    } finally {
        Remove-Item -LiteralPath $temporaryToken -Force -ErrorAction SilentlyContinue
    }
} else {
    & wsl.exe -d Ubuntu-24.04 -- bash "$root/scripts/ngrok-tunnel.sh" $Operation
}
if ($LASTEXITCODE -ne 0) { throw "ngrok $Operation failed" }
