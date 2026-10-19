param([Parameter(Mandatory=$true)][string]$EvidenceDir)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
Set-Location -LiteralPath $repoRoot
$evidenceRoot = [IO.Path]::GetFullPath($EvidenceDir)
if (Test-Path -LiteralPath $evidenceRoot) { throw 'Choose a fresh external evidence directory; earlier evidence is retained.' }
& node --input-type=module -e "import { ownRoot } from './tools/product-curator/safety.mjs'; await ownRoot(process.argv[1]);" $evidenceRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$env:FURNITUREOS_EVIDENCE_DIR = $evidenceRoot
Remove-Item Env:VERCEL_OIDC_TOKEN -ErrorAction SilentlyContinue
$configFile = Join-Path $repoRoot 'playwright.config.ts'
$playwrightCli = Join-Path $repoRoot 'node_modules/@playwright/test/cli.js'
$pythonExe = Join-Path $repoRoot '.venv/Scripts/python.exe'
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$listener.Start()
$webPort = $listener.LocalEndpoint.Port
$listener.Stop()
$env:E2E_BASE_URL = 'http://127.0.0.1:' + $webPort

function Invoke-ProofStep {
  param([string]$Name, [string]$File, [string[]]$Arguments, [string]$Directory = $repoRoot)
  Push-Location -LiteralPath $Directory
  try {
    $null = Get-Command $File -ErrorAction Stop
    # Windows PowerShell wraps native stderr warnings as ErrorRecords. The
    # native exit code remains authoritative; preserve both streams in the log.
    $ErrorActionPreference = 'Continue'
    & $File @Arguments *> (Join-Path $evidenceRoot ($Name + '.log'))
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    @{ name = $Name; executable = $File; arguments = $Arguments; cwd = $Directory; exitCode = $code } | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $evidenceRoot 'commands.jsonl')
    Write-Output ($Name + ' exit=' + $code)
    return $code
  } finally { $ErrorActionPreference = 'Stop'; Pop-Location }
}
function Invoke-BrowserSuite {
  param([string]$Name, [bool]$Gallery)
  if ($Gallery) { $env:FURNITUREOS_ENABLE_CATALOGUE_GALLERY = '1' }
  else { Remove-Item Env:FURNITUREOS_ENABLE_CATALOGUE_GALLERY -ErrorAction SilentlyContinue }
  $serverProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', $webPort) -WorkingDirectory $repoRoot -RedirectStandardOutput (Join-Path $evidenceRoot ($Name + '-server.stdout.log')) -RedirectStandardError (Join-Path $evidenceRoot ($Name + '-server.stderr.log')) -PassThru -WindowStyle Hidden
  try {
    $deadline = (Get-Date).AddSeconds(45)
    do {
      try { if ((Invoke-WebRequest -UseBasicParsing ($env:E2E_BASE_URL + '/api/health')).StatusCode -eq 200) { break } } catch {}
      Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    if ((Get-Date) -ge $deadline) { throw 'Owned loopback API failed to start; retained server logs explain the failure.' }
    $filter = if ($Gallery) { '--grep' } else { '--grep-invert' }
    # Bound the shared solver and SwiftShader workload to one browser worker.
    $workers = '--workers=1'
    # External cwd also relocates the legacy landing screenshot test's hardcoded
    # process.cwd()/test-results path without changing that production test.
    $result = Invoke-ProofStep -Name $Name -File 'node' -Arguments @($playwrightCli, 'test', '--config', $configFile, $filter, '@measurement', $workers, '--output', (Join-Path $evidenceRoot ($Name + '-output'))) -Directory $evidenceRoot
    return $result[-1]
  } finally {
    if ($serverProcess -and -not $serverProcess.HasExited) { Stop-Process -Id $serverProcess.Id -Force }
  }
}
$testExit = 1
try {
  $result = Invoke-ProofStep -Name 'normal-build-before' -File 'npm.cmd' -Arguments @('run', 'build')
  if ($result[-1] -ne 0) { exit $result[-1] }
  $testExit = Invoke-BrowserSuite -Name 'ordinary-browser' -Gallery $false
  if ($testExit -ne 0) { exit $testExit }
  $result = Invoke-ProofStep -Name 'measurement-build' -File 'npm.cmd' -Arguments @('run', 'build:measurement')
  if ($result[-1] -ne 0) { exit $result[-1] }
  Copy-Item -LiteralPath (Join-Path $repoRoot 'dist/measurement-build.json') -Destination (Join-Path $evidenceRoot 'measurement-build.json')
  $testExit = Invoke-BrowserSuite -Name 'measurement-browser' -Gallery $true
} finally {
  Remove-Item Env:FURNITUREOS_ENABLE_CATALOGUE_GALLERY -ErrorAction SilentlyContinue
  $result = Invoke-ProofStep -Name 'normal-build-restored' -File 'npm.cmd' -Arguments @('run', 'build')
  if ($result[-1] -ne 0 -and $testExit -eq 0) { $testExit = $result[-1] }
}
exit $testExit
