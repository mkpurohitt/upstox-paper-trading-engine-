param(
  [switch]$SkipLoginPages
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Local = Join-Path $Root ".local"
$Logs = Join-Path $Local "logs"
$PidFile = Join-Path $Local "pids.json"

New-Item -ItemType Directory -Force -Path $Local, $Logs | Out-Null

function Require-Command($Name, $InstallHint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "$Name was not found. $InstallHint"
  }
}

function Wait-Url($Url, $Name, $TimeoutSeconds = 90) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 | Out-Null
      Write-Host "$Name is ready: $Url"
      return
    } catch {
      Start-Sleep -Seconds 2
    }
  }
  throw "$Name did not become ready within $TimeoutSeconds seconds. Check logs in $Logs"
}

Write-Host "Stopping old project processes if any..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "stop_full_system.ps1") -Quiet

Require-Command "python" "Install Python 3.11+ and reopen PowerShell."
Require-Command "node" "Install Node.js 20+ and reopen PowerShell."
Require-Command "npm" "Install Node.js 20+ and reopen PowerShell."

Write-Host "Installing backend requirements..."
Set-Location $Backend
if (-not (Test-Path ".venv")) {
  python -m venv .venv
}
$BackendPython = Join-Path $Backend ".venv\Scripts\python.exe"
& $BackendPython -m pip install --upgrade pip
& $BackendPython -m pip install -r requirements.txt

Write-Host "Installing frontend requirements..."
Set-Location $Frontend
& npm install

Write-Host "Starting backend..."
$BackendCommand = "`$env:PYTHONPATH='.'; & '$BackendPython' -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
$BackendProc = Start-Process `
  -FilePath "powershell.exe" `
  -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $BackendCommand) `
  -WorkingDirectory $Backend `
  -RedirectStandardOutput (Join-Path $Logs "backend.out.log") `
  -RedirectStandardError (Join-Path $Logs "backend.err.log") `
  -WindowStyle Hidden `
  -PassThru

Wait-Url "http://localhost:8000/health" "Backend"

Write-Host "Starting frontend..."
$FrontendProc = Start-Process `
  -FilePath "npm.cmd" `
  -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1") `
  -WorkingDirectory $Frontend `
  -RedirectStandardOutput (Join-Path $Logs "frontend.out.log") `
  -RedirectStandardError (Join-Path $Logs "frontend.err.log") `
  -WindowStyle Hidden `
  -PassThru

Wait-Url "http://localhost:5173" "Frontend"

@{
  backend = $BackendProc.Id
  frontend = $FrontendProc.Id
  started_at = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content -Path $PidFile -Encoding UTF8

if (-not $SkipLoginPages) {
  Write-Host "Opening Live Login, Sandbox Apps, and Dashboard..."
  Start-Process "http://localhost:8000/auth/login/redirect?mode=live&state=paper-platform-live"
  Start-Sleep -Seconds 2
  Start-Process "https://account.upstox.com/developer/apps"
  Start-Sleep -Seconds 2
  Start-Process "http://localhost:5173"
} else {
  Start-Process "http://localhost:5173"
}

Write-Host ""
Write-Host "System started."
Write-Host "Authorize Live in the browser tab. Live token will save to .local\upstox_tokens.json."
Write-Host "For sandbox, generate a sandbox access token in Upstox Developer Apps and paste it in UPSTOX_SANDBOX_ACCESS_TOKEN."
Write-Host "Dashboard: http://localhost:5173"
Write-Host "Backend API: http://localhost:8000/docs"
Write-Host "Logs: $Logs"
Write-Host "Stop command: .\scripts\stop_full_system.bat"
