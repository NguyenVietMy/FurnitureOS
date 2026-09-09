$ErrorActionPreference = 'Stop'

if ($env:E2E_BASE_URL) {
  & npx.cmd playwright test
  exit $LASTEXITCODE
}

npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$webPort = 3101
$uvicorn = Join-Path $PSScriptRoot '..\.venv\Scripts\uvicorn.exe'
$server = Start-Process -FilePath $uvicorn -ArgumentList @('api.main:app', '--host', '127.0.0.1', '--port', $webPort) -PassThru -WindowStyle Hidden
$testExit = 1
try {
  $deadline = (Get-Date).AddSeconds(45)
  do {
    try { if ((Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$webPort/api/health").StatusCode -eq 200 -and (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$webPort/").StatusCode -eq 200) { break } } catch {}
    Start-Sleep -Milliseconds 250
  } while ((Get-Date) -lt $deadline)
  if ((Get-Date) -ge $deadline) { throw 'Timed out starting the full FastAPI server.' }
  & npx.cmd playwright test
  $testExit = $LASTEXITCODE
} finally {
  if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
}
exit $testExit
