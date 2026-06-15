# Launch the ReEDS Surrogate Bokeh dashboard.
# If the server is already running on port 5006, just opens the browser.
# Otherwise starts a hidden Bokeh server, waits for it to be ready, then opens
# the browser to http://localhost:5006/surrogate_dashboard.
#
# This script is invoked by ../Open Dashboard.bat (double-click target).

$ErrorActionPreference = "Stop"
$here       = Split-Path -Parent $MyInvocation.MyCommand.Definition
$studyRoot  = Split-Path -Parent $here
$bokehExe   = "C:\Users\ychen10\AppData\Local\anaconda3\Scripts\bokeh.exe"
$dashScript = Join-Path $here "surrogate_dashboard.py"
$logDir     = Join-Path $studyRoot "logs"
$port       = 5006
$url        = "http://localhost:$port/surrogate_dashboard"

if (-not (Test-Path $bokehExe)) {
    Write-Host "ERROR: bokeh.exe not found at $bokehExe" -ForegroundColor Red
    Write-Host "Edit launch_dashboard.ps1 to point at your bokeh install."
    Read-Host "Press Enter to close"
    exit 1
}
if (-not (Test-Path $dashScript)) {
    Write-Host "ERROR: dashboard script not found at $dashScript" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

$listening = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "Bokeh server already running on port $port (pid $($listening[0].OwningProcess)). Opening browser..." -ForegroundColor Green
} else {
    Write-Host "Starting Bokeh server on port $port..." -ForegroundColor Yellow
    Start-Process -FilePath $bokehExe `
        -ArgumentList @("serve", $dashScript, "--port", "$port",
                        "--allow-websocket-origin=localhost:$port",
                        "--allow-websocket-origin=127.0.0.1:$port") `
        -RedirectStandardOutput (Join-Path $logDir "dashboard.out") `
        -RedirectStandardError  (Join-Path $logDir "dashboard.err") `
        -WindowStyle Hidden | Out-Null

    # Wait up to ~20s for the port to come up
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
            $ready = $true
            break
        }
    }
    if ($ready) {
        Write-Host "Server ready. Opening browser..." -ForegroundColor Green
    } else {
        Write-Host "WARNING: server did not start within 20s. Check $logDir\dashboard.err" -ForegroundColor Red
        Read-Host "Press Enter to close"
        exit 1
    }
}

Start-Process $url
Start-Sleep -Seconds 2  # give browser a moment to launch before window closes
