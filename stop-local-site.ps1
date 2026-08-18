$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $projectDir ".local-site\server.pid"

if (-not (Test-Path -LiteralPath $pidFile)) {
  Write-Host "The local website is not running."
  Start-Sleep -Seconds 2
  exit 0
}

$sitePid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue
if ($sitePid -and (Get-Process -Id $sitePid -ErrorAction SilentlyContinue)) {
  & taskkill.exe /PID $sitePid /T /F | Out-Null
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Write-Host "The local website has stopped."
Start-Sleep -Seconds 2
