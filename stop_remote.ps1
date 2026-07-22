[CmdletBinding()]
param(
    [string]$Subdomain = "valuation-grid"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$ProjectRoot = $PSScriptRoot
$AppPath = Join-Path $ProjectRoot "app.py"
$escapedAppPath = [regex]::Escape($AppPath)
$fullAppPattern = '(?i)' + $escapedAppPath + '(?:[\s"]|$)'
$subdomainPattern = "--subdomain\s+$([regex]::Escape($Subdomain))(?:\s|$)"
$all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)

$targetIds = [System.Collections.Generic.HashSet[int]]::new()
foreach ($process in $all) {
    $isApp = $process.Name -match '^python(?:w)?\.exe$' -and
        $process.CommandLine -and $process.CommandLine -match $fullAppPattern
    $isTunnel = $process.CommandLine -and
        $process.CommandLine -match '(?i)localtunnel' -and
        $process.CommandLine -match $subdomainPattern
    if ($isApp -or $isTunnel) {
        [void]$targetIds.Add([int]$process.ProcessId)
    }
}

do {
    $added = $false
    foreach ($process in $all) {
        if ($targetIds.Contains([int]$process.ParentProcessId) -and
            -not $targetIds.Contains([int]$process.ProcessId)) {
            [void]$targetIds.Add([int]$process.ProcessId)
            $added = $true
        }
    }
} while ($added)

foreach ($processId in @($targetIds) | Sort-Object -Descending) {
    if ($processId -ne $PID) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

$deadline = (Get-Date).AddSeconds(10)
do {
    $remaining = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $targetIds.Contains([int]$_.ProcessId)
    })
    if ($remaining.Count -eq 0) {
        Write-Host "valuation-grid stopped safely; position data was not modified." -ForegroundColor Green
        exit 0
    }
    Start-Sleep -Milliseconds 200
} while ((Get-Date) -lt $deadline)

$remainingIds = @($remaining | Select-Object -ExpandProperty ProcessId) -join ', '
throw "valuation-grid processes are still running: $remainingIds"
