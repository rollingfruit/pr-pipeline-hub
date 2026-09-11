$ErrorActionPreference = 'Stop'
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$settings = Get-ItemProperty $key
$backup = Join-Path $PSScriptRoot '../.runtime/proxy-before-ecs-direct.json'
if (-not (Test-Path $backup)) {
    $settings | Select-Object ProxyEnable,ProxyServer,ProxyOverride |
        ConvertTo-Json | Set-Content -LiteralPath $backup -Encoding UTF8
}
$items = @($settings.ProxyOverride -split ';' | Where-Object { $_ })
if ($items -notcontains '119.8.233.58') {
    Set-ItemProperty -Path $key -Name ProxyOverride -Value (($items + '119.8.233.58') -join ';')
}
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class EcsProxyRefresh {
    [DllImport("wininet.dll", SetLastError=true)]
    public static extern bool InternetSetOption(IntPtr handle, int option, IntPtr buffer, int length);
}
'@
[void][EcsProxyRefresh]::InternetSetOption([IntPtr]::Zero,39,[IntPtr]::Zero,0)
[void][EcsProxyRefresh]::InternetSetOption([IntPtr]::Zero,37,[IntPtr]::Zero,0)
Write-Output 'Added only 119.8.233.58 to the existing proxy bypass list; proxy remains enabled.'
