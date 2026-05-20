param(
  [switch]$Quiet
)

$ErrorActionPreference = "SilentlyContinue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PidFile = Join-Path $Root ".local\pids.json"

function Stop-ProcessTree($ProcessId) {
  if (-not $ProcessId) {
    return
  }
  Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" | ForEach-Object {
    Stop-ProcessTree $_.ProcessId
  }
  Stop-Process -Id $ProcessId -Force
}

if (Test-Path $PidFile) {
  $pids = Get-Content -Raw -Path $PidFile | ConvertFrom-Json
  Stop-ProcessTree $pids.backend
  Stop-ProcessTree $pids.frontend
  Remove-Item -Path $PidFile -Force
}

if (-not $Quiet) {
  Write-Host "System stopped."
}

