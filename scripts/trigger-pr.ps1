[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PrUrl,
    [string]$RequestedBy = "multica-agent",
    [string]$BaseUrl = "http://127.0.0.1:8787",
    [string]$TriggerToken = $env:PIPELINE_TRIGGER_TOKEN
)

$headers = @{}
if ($TriggerToken) {
    $headers["X-Pipeline-Token"] = $TriggerToken
}
$payload = @{
    pr_url = $PrUrl
    requested_by = $RequestedBy
} | ConvertTo-Json

$run = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/runs" -Headers $headers -ContentType "application/json" -Body $payload
$run | ConvertTo-Json -Depth 8

