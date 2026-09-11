[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PrUrl,
    [Parameter(Mandatory)][string]$MessageId,
    [Parameter(Mandatory)][string]$GroupId,
    [Parameter(Mandatory)][string]$RequestedBy,
    [Parameter(Mandatory)][string]$AgentConfig,
    [switch]$Wait
)
$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath $AgentConfig | ConvertFrom-Json
if (-not $config.base_url -or -not $config.trigger_token -or -not $config.view_token) {
    throw 'A dedicated E2E endpoint with trigger/view credentials is required.'
}
if (-not $config.group_id -or $config.group_id -ne $GroupId -or $config.bot_name -ne 'xiao-commitor') {
    throw 'Group or robot binding does not match the configured E2E integration.'
}
$headers = @{'X-Pipeline-Token' = $config.trigger_token}
$base = $config.base_url.TrimEnd('/')
$body = @{
    pr_url = $PrUrl; requested_by = $RequestedBy; profile = 'browser-e2e'
    request_id = "newlink:$GroupId`:$MessageId"
} | ConvertTo-Json
$run = Invoke-RestMethod -NoProxy -Method Post -Uri "$base/api/runs" -Headers $headers -ContentType application/json -Body $body
$uri = [Uri]$run.web_url
if (-not $uri.IsAbsoluteUri -or $uri.Scheme -notin @('http', 'https') -or $uri.IsLoopback) {
    throw "Run $($run.id) exists, but its link is not a group-shareable HTTP(S) URL. Do not resubmit with another message ID."
}
# Return the durable link before waiting. The caller delivers it through its existing group task.
@{event='queued'; run_id=$run.id; web_url=$run.web_url; queue_position=$run.queue_position} | ConvertTo-Json -Compress
if (-not $Wait) { return }
$view = @{'X-Pipeline-View-Token' = $config.view_token}
$deadline = (Get-Date).AddHours(8)
do {
    $run = Invoke-RestMethod -NoProxy -Uri "$base/api/runs/$($run.id)" -Headers $view
    if ($run.status -in @('completed', 'interrupted')) {
        @{event='finished'; run_id=$run.id; web_url=$run.web_url; conclusion=$run.conclusion
          summary=$run.summary; github=$run.github; merge_conflicts=$run.merge_conflicts} | ConvertTo-Json -Depth 6 -Compress
        return
    }
    Start-Sleep -Seconds 5
} while ((Get-Date) -lt $deadline)
throw "Wait timed out; the queued run remains at $($run.web_url)."
