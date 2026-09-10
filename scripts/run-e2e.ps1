$ErrorActionPreference = 'Stop'

if ($env:E2E_BASE_URL) {
  & npx.cmd playwright test
  exit $LASTEXITCODE
}

$webPort = 3101
$uvicorn = Join-Path $PSScriptRoot '..\.venv\Scripts\uvicorn.exe'
$artifactRoot = if ($env:FURNITUREOS_EVIDENCE_DIR) {
  $env:FURNITUREOS_EVIDENCE_DIR
} else {
  Join-Path $env:TEMP 'astra-loop\ticket-2\evidence'
}
$env:FURNITUREOS_EVIDENCE_DIR = $artifactRoot
New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null

function Invoke-BrowserSuite {
  param(
    [string[]]$PlaywrightArguments,
    [bool]$GalleryEnabled
  )
  if ($GalleryEnabled) {
    $env:FURNITUREOS_ENABLE_CATALOGUE_GALLERY = '1'
  } else {
    Remove-Item Env:FURNITUREOS_ENABLE_CATALOGUE_GALLERY -ErrorAction SilentlyContinue
  }
  $server = Start-Process -FilePath $uvicorn -ArgumentList @('api.main:app', '--host', '127.0.0.1', '--port', $webPort) -PassThru -WindowStyle Hidden
  try {
    $deadline = (Get-Date).AddSeconds(45)
    do {
      try {
        if ((Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$webPort/api/health").StatusCode -eq 200) { break }
      } catch {}
      Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    if ((Get-Date) -ge $deadline) { throw 'Timed out starting the full FastAPI server.' }
    & npx.cmd playwright test @PlaywrightArguments | Out-Host
    $playwrightExit = $LASTEXITCODE
    return $playwrightExit
  } finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
  }
}

$testExit = 1
try {
  npm run build
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  $testExit = Invoke-BrowserSuite -PlaywrightArguments @('--grep-invert', '@measurement') -GalleryEnabled $false
  if ($testExit -ne 0) { exit $testExit }

  npm run build:measurement
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\dist\measurement-build.json') -Destination (Join-Path $artifactRoot 'measurement-build.json') -Force
  $testExit = Invoke-BrowserSuite -PlaywrightArguments @('--grep', '@measurement', '--workers=1') -GalleryEnabled $true
} finally {
  Remove-Item Env:FURNITUREOS_ENABLE_CATALOGUE_GALLERY -ErrorAction SilentlyContinue
  npm run build
  if ($LASTEXITCODE -ne 0 -and $testExit -eq 0) { $testExit = $LASTEXITCODE }
}
exit $testExit
