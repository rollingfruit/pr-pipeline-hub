$ErrorActionPreference = 'Stop'
$workspace = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$running = Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" | Where-Object {
    $_.CommandLine -match 'Ubuntu-24.04.*sleep.*infinity'
}
if (-not $running) {
    Start-Process wsl.exe -ArgumentList '-d','Ubuntu-24.04','--','sleep','infinity' -WindowStyle Hidden | Out-Null
}
& (Join-Path $workspace 'mattermost-microservice/infra/pr-e2e/start-model.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Local subscribed model startup failed' }
& wsl.exe -d Ubuntu-24.04 -- systemctl start pr-e2e-local-hub pr-local-selection pr-github-monitor pr-e2e-publisher
if ($LASTEXITCODE -ne 0) { throw 'Pipeline service startup failed' }
$response = Invoke-WebRequest 'http://127.0.0.1:8793/' -TimeoutSec 20
if ($response.StatusCode -ne 200) { throw 'Local batch editor is not reachable' }
Write-Output 'Local batch editor: http://127.0.0.1:8793/'
Write-Output 'Shared read-only dashboard: http://119.8.233.58:8080/batches'
