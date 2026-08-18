$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $projectDir ".local-site"
$pidFile = Join-Path $runtimeDir "server.pid"
$outputLog = Join-Path $runtimeDir "server.log"
$errorLog = Join-Path $runtimeDir "server-error.log"
$siteUrl = "http://127.0.0.1:3100/"
$vinextCli = Join-Path $projectDir "node_modules\vinext\dist\cli.js"

function Show-ErrorAndWait([string]$message) {
  Write-Host ""
  Write-Host $message -ForegroundColor Red
  Write-Host ""
  Read-Host "Press Enter to close"
  exit 1
}

try {
  $existing = Invoke-WebRequest -UseBasicParsing -Uri $siteUrl -TimeoutSec 2
  if ($existing.StatusCode -eq 200) {
    Start-Process $siteUrl
    exit 0
  }
} catch {
  # The local site is not running yet.
}

$nodeFromPath = Get-Command node.exe -ErrorAction SilentlyContinue
$nodeCandidates = @(
  $(if ($nodeFromPath) { $nodeFromPath.Source }),
  (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

$nodeExe = $nodeCandidates | Select-Object -First 1
if (-not $nodeExe) {
  Show-ErrorAndWait "Node.js was not found. Install Node.js 22 or reopen this project in Codex."
}

if (-not (Test-Path -LiteralPath $vinextCli)) {
  Show-ErrorAndWait "Website dependencies are incomplete. Ask Codex to reinstall local dependencies."
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$env:Path = "$(Split-Path -Parent $nodeExe);$env:Path"

$server = Start-Process `
  -FilePath $nodeExe `
  -ArgumentList @($vinextCli, "dev", "--host", "127.0.0.1", "--port", "3100", "--strictPort") `
  -WorkingDirectory $projectDir `
  -WindowStyle Hidden `
  -RedirectStandardOutput $outputLog `
  -RedirectStandardError $errorLog `
  -PassThru

Set-Content -LiteralPath $pidFile -Value $server.Id -Encoding ascii

for ($attempt = 0; $attempt -lt 30; $attempt++) {
  Start-Sleep -Milliseconds 500
  if ($server.HasExited) {
    $details = if (Test-Path -LiteralPath $errorLog) { Get-Content -Raw -LiteralPath $errorLog } else { "Unknown error" }
    Show-ErrorAndWait "Local website failed to start: $details"
  }

  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $siteUrl -TimeoutSec 2
    if ($response.StatusCode -eq 200) {
      Start-Process $siteUrl
      exit 0
    }
  } catch {
    # Keep waiting for the local server.
  }
}

Show-ErrorAndWait "Local website startup timed out. Check the .local-site log files."

