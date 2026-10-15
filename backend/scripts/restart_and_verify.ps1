$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $taskRoot

# Resolve and validate the exact listeners before stopping anything.
foreach ($taskPort in @(8000, 5173)) {
    $taskListeners = @(Get-NetTCPConnection -LocalPort $taskPort -State Listen -ErrorAction SilentlyContinue)
    foreach ($taskListener in $taskListeners) {
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($taskListener.OwningProcess)"
        $taskExpected = if ($taskPort -eq 8000) {
            $taskProcess.CommandLine -match 'uvicorn\s+app\.main:app'
        } else {
            # npm may launch Vite with a relative command line (for example
            # `node_modules/vite/bin/vite.js`), so the frontend path is not
            # guaranteed to appear in the listener's own command line. The
            # listener is already constrained to the task's dedicated port.
            $taskProcess.CommandLine -match 'vite'
        }
        if (-not $taskExpected) { throw "Port $taskPort belongs to an unrecognized process; nothing will be stopped." }
    }
}
foreach ($taskPort in @(8000, 5173)) {
    Get-NetTCPConnection -LocalPort $taskPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Process -Id $_ -ErrorAction Stop }
}

python (Join-Path $PSScriptRoot 'start_local_services.py')
if ($LASTEXITCODE -ne 0) { throw 'Service launch failed.' }
$taskReady = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $taskHealth = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 2
        $taskFront = Invoke-WebRequest 'http://127.0.0.1:5173/runtime' -UseBasicParsing -TimeoutSec 2
        if ($taskHealth.service -eq 'weknora-python' -and $taskFront.StatusCode -eq 200) { $taskReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not $taskReady) { throw 'Service health check failed; inspect data/runtime-check logs.' }
Write-Output 'Backend and frontend: HTTP 200. Testing actual model APIs now.'
python (Join-Path $PSScriptRoot 'verify_model_chain.py')
exit $LASTEXITCODE
