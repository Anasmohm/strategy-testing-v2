$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DashboardUrl = "http://127.0.0.1:8782/reports/paper_portfolio_v2_dashboard.html"

Set-Location $Root

function Test-LocalPort {
    param([int] $Port)

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $connected = $result.AsyncWaitHandle.WaitOne(500)
        if ($connected) {
            $client.EndConnect($result)
        }
        return $connected
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python is not available in PATH." -ForegroundColor Red
    Write-Host "Install Python or add it to PATH, then run start_dashboard_v2.bat again."
    exit 1
}

Write-Host "Starting Strategy Testing V2 dashboard..."
Write-Host "Project: $Root"

if (-not (Test-LocalPort 8766)) {
    Write-Host "Starting settings server on 127.0.0.1:8766..."
    Start-Process -FilePath "python" -ArgumentList "settings_server_v2.py" -WorkingDirectory $Root -WindowStyle Minimized
}
else {
    Write-Host "Settings server is already running on 127.0.0.1:8766."
}

if (-not (Test-LocalPort 8782)) {
    Write-Host "Starting local dashboard server on 127.0.0.1:8782..."
    Start-Process -FilePath "python" -ArgumentList @("-m", "http.server", "8782", "--bind", "127.0.0.1") -WorkingDirectory $Root -WindowStyle Minimized
}
else {
    Write-Host "Local dashboard server is already running on 127.0.0.1:8782."
}

Start-Sleep -Seconds 2
Start-Process $DashboardUrl

Write-Host ""
Write-Host "Dashboard opened:"
Write-Host $DashboardUrl -ForegroundColor Cyan
Write-Host ""
Write-Host "You can close this window. The local servers will keep running in separate minimized windows."
