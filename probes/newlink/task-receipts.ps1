param([string]$Marker = 'NL-20260909-01', [string]$TaskId = '')
$ErrorActionPreference = 'Stop'
$tokenPath = Join-Path $env:USERPROFILE '.multica/local-collab/view_token'
$token = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
$uri = 'http://127.0.0.1:19514/api/local-collab/tasks?token=' + [uri]::EscapeDataString($token)
$response = Invoke-RestMethod -Uri $uri -TimeoutSec 15
$tasks = @($response.tasks | Where-Object {
    $_.agent_id -eq '2b6d5bef-1a74-4e13-8638-eb64ea35e869' -and
    $_.workspace_id -eq 'f599cfe5-bc2b-4900-bf05-5e2dbe18a431'
})
$matched = @($tasks | Where-Object {
    if ($TaskId) { $_.task_id -eq $TaskId }
    else { ($_ | ConvertTo-Json -Depth 30 -Compress).Contains($Marker) }
})
[pscustomobject]@{
    marker = $Marker
    requested_task_id = $TaskId
    observed_at = [DateTime]::UtcNow.ToString('o')
    matched_count = $matched.Count
    tasks = @($matched | Select-Object task_id, workspace_id, agent_id, agent_name, provider, status, started_at, updated_at)
    note = 'Pre-spawn failures may be absent here. Also inspect daemon-receipts.py using the real task ID. Ack is not final success.'
} | ConvertTo-Json -Depth 5
