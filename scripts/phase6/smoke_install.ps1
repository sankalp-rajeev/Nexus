<#
.SYNOPSIS
  Clean-venv smoke test of the nexus-llmops distribution (no repo code on the client side).

.DESCRIPTION
  1. Creates a fresh venv and installs nexus-llmops from -Source:
       local     the wheel built in sdk\dist (nexus-llmops itself is NOT fetched from any index;
                 only its two third-party dependencies are downloaded into a wheelhouse first)
       testpypi  https://test.pypi.org/simple/ (dependencies from pypi.org), pinned to -Version
  2. Checks the install: the package comes from the venv, the alias works, server-side code is absent.
  3. Collector UP: starts the lite collector (in-process queue, SQLite, no Kafka, no LLM) and runs a
     small traced program with the SDK from the venv. Spans must arrive and be classified (a loop).
  4. Collector DOWN: stops the collector and runs the same program. It must finish normally, and the
     SDK counters must show the drops.
  5. Uninstalls the package and checks the import is gone.

  Writes data\phase6\runs\scratch\smoke_<source>.json and exits non-zero on any failed check.
  The venv is left in place (under data\phase6\runs\scratch\smoke) and never deleted by this script.

.EXAMPLE
  powershell -File scripts\phase6\smoke_install.ps1 -Source local
  powershell -File scripts\phase6\smoke_install.ps1 -Source testpypi -Version 0.1.0rc1
#>
param(
    [ValidateSet('local', 'testpypi')][string]$Source = 'local',
    [string]$Version = '0.1.0rc1',
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$RepoPython = Join-Path $Repo '.venv\Scripts\python.exe'   # runs the collector side only
$Scratch = Join-Path $Repo 'data\phase6\runs\scratch\smoke'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Work = Join-Path $Scratch "$Source-$Stamp"
$Venv = Join-Path $Work 'venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$Url = "http://127.0.0.1:$Port"
$Report = [ordered]@{ source = $Source; version = $Version; started = (Get-Date).ToString('o'); checks = [ordered]@{} }
$Failures = New-Object System.Collections.Generic.List[string]
New-Item -ItemType Directory -Force -Path $Work | Out-Null

function Say($text) { Write-Host $text }
function Check([string]$name, [bool]$ok, $detail = '') {
    $Report.checks[$name] = [ordered]@{ ok = $ok; detail = "$detail" }
    if ($ok) { Say "PASS  $name  $detail" } else { Say "FAIL  $name  $detail"; $Failures.Add($name) }
}
# Run a native command, capture stdout+stderr as text, never throw on stderr noise.
function Run([string]$exe, [string[]]$arguments, [hashtable]$env = @{}, [string]$cwd = $Work) {
    $saved = @{}
    foreach ($k in $env.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $env[$k]) }
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    Push-Location $cwd
    try { $out = & $exe @arguments 2>&1 | ForEach-Object { "$_" } | Out-String; $code = $LASTEXITCODE }
    finally { Pop-Location; $ErrorActionPreference = $prev
        foreach ($k in $env.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) } }
    return [pscustomobject]@{ Code = $code; Out = $out.Trim() }
}

# --- the client program (runs inside the clean venv) ------------------------------------------
$Program = @'
import json, sys, time
import nexus_llmops as nexus
import nexus_agent
assert nexus_agent is nexus, "alias must be the same module"
url = sys.argv[1]
started = time.perf_counter()
client = nexus.init(agent_name="smoke", collector_url=url, export_timeout_ms=500)

@nexus.trace(span_type="tool_call", tool_name="lookup")
def lookup(order_id):
    return "order %s: shipped" % order_id

@nexus.trace(span_type="llm_call", model="demo")
def summarise(text):
    return "summary of " + text

@nexus.trace(span_type="agent_step")
def run(task):
    out = [lookup(42), lookup(42), lookup(42)]   # three identical calls: a loop
    return summarise(" ".join(out))

result = run("where is order 42")
nexus.flush()
elapsed = time.perf_counter() - started
stats = client.stats
nexus.shutdown()
print("RESULT " + json.dumps({"program_result": result, "elapsed_s": round(elapsed, 2),
                              "version": nexus.__version__, "file": nexus.__file__, "stats": stats}))
'@
$ProgramPath = Join-Path $Work 'smoke_program.py'
Set-Content -Path $ProgramPath -Value $Program -Encoding ASCII

# --- 1. venv + install --------------------------------------------------------------------------
Say "== smoke: source=$Source version=$Version work=$Work"
$r = Run $RepoPython @('-m', 'venv', $Venv)
Check 'venv created' ($r.Code -eq 0 -and (Test-Path $VenvPython)) $r.Out
if ($Source -eq 'local') {
    $wheel = Join-Path $Repo "sdk\dist\nexus_llmops-$Version-py3-none-any.whl"
    Check 'wheel present' (Test-Path $wheel) $wheel
    $wheelhouse = Join-Path $Work 'wheelhouse'
    # Third-party dependencies only; nexus-llmops itself is installed from the local file.
    $r = Run $VenvPython @('-m', 'pip', 'download', '--quiet', '--dest', $wheelhouse, 'httpx>=0.27', 'pydantic>=2.7')
    Check 'dependency wheelhouse' ($r.Code -eq 0) $r.Out
    $r = Run $VenvPython @('-m', 'pip', 'install', '--quiet', '--no-index', '--find-links', $wheelhouse, '--find-links', (Split-Path $wheel), $wheel)
} else {
    $r = Run $VenvPython @('-m', 'pip', 'install', '--quiet', '--pre', '--index-url', 'https://test.pypi.org/simple/',
        '--extra-index-url', 'https://pypi.org/simple/', "nexus-llmops==$Version")
}
Check 'pip install' ($r.Code -eq 0) $r.Out

# --- 2. install checks (cwd is outside the repo, so nothing from the repo can be imported) ------
$probe = "import json, nexus_llmops, nexus_agent, nexus_agent.models as m, nexus_llmops.models as n, importlib.util as u; " +
         "print(json.dumps({'file': nexus_llmops.__file__, 'version': nexus_llmops.__version__, 'alias_same': nexus_agent is nexus_llmops and m is n, " +
         "'integrations': u.find_spec('nexus_llmops.integrations') is not None, 'collector_code': u.find_spec('services') is not None}))"
$r = Run $VenvPython @('-c', $probe)
$info = $null
try { $info = $r.Out | ConvertFrom-Json } catch { }
Check 'import from the venv' ($null -ne $info -and $info.file -like "$Venv*") $r.Out
if ($info) {
    Check 'version matches' ($info.version -eq $Version) $info.version
    Check 'alias is the same module objects' ([bool]$info.alias_same)
    Check 'no server-side code in the wheel' (-not $info.integrations -and -not $info.collector_code)
}
$r = Run $VenvPython @('-m', 'pip', 'list', '--format=freeze')
$Report['installed_packages'] = ($r.Out -split "`r?`n")
$unexpected = $Report['installed_packages'] | Where-Object { $_ -match '^(opentelemetry|protobuf|torch|transformers|fastapi|confluent)' }
Check 'no heavy or server dependencies pulled in' (-not $unexpected) ($unexpected -join ', ')

# --- 3. collector UP ----------------------------------------------------------------------------
$db = Join-Path $Work 'lite.db'
$collectorEnv = @{ NEXUS_QUEUE = 'inprocess'; NEXUS_SQLITE_PATH = $db; NEXUS_LLM = 'mock'; PYTHONPATH = "$Repo;$Repo\sdk" }
foreach ($k in $collectorEnv.Keys) { [Environment]::SetEnvironmentVariable($k, $collectorEnv[$k]) }
$collector = Start-Process -FilePath $RepoPython -WorkingDirectory $Repo -PassThru -WindowStyle Hidden `
    -ArgumentList @('-m', 'uvicorn', 'services.collector.main:app', '--host', '127.0.0.1', '--port', "$Port", '--workers', '1') `
    -RedirectStandardOutput (Join-Path $Work 'collector.out.log') -RedirectStandardError (Join-Path $Work 'collector.err.log')
foreach ($k in $collectorEnv.Keys) { [Environment]::SetEnvironmentVariable($k, $null) }
$up = $false
for ($i = 0; $i -lt 60 -and -not $up; $i++) {
    Start-Sleep -Milliseconds 500
    try { $up = ((Invoke-WebRequest "$Url/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) } catch { }
}
Check 'lite collector started' $up "$Url (pid $($collector.Id))"

function Count-Rows([string]$sql) {
    $code = "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute(sys.argv[2]).fetchone()[0])"
    $o = Run $RepoPython @('-c', $code, $db, $sql)
    if ($o.Code -ne 0) { return -1 } else { return [int]$o.Out }
}

$runUp = Run $VenvPython @($ProgramPath, $Url)
$resultUp = $null
foreach ($line in ($runUp.Out -split "`r?`n")) { if ($line.StartsWith('RESULT ')) { $resultUp = $line.Substring(7) | ConvertFrom-Json } }
Check 'program finished (collector up)' ($runUp.Code -eq 0 -and $null -ne $resultUp) $runUp.Out
if ($resultUp) {
    Check 'all spans exported' ($resultUp.stats.produced -eq 5 -and $resultUp.stats.exported -eq 5 -and $resultUp.stats.dropped_total -eq 0) ($resultUp.stats | ConvertTo-Json -Compress)
    $Report['program_up'] = $resultUp
}
$spans = 0; $alerts = 0; $traces = 0
for ($i = 0; $i -lt 20; $i++) {
    $spans = Count-Rows 'SELECT COUNT(*) FROM spans'
    $alerts = Count-Rows "SELECT COUNT(*) FROM artifacts WHERE kind='alerts' AND body LIKE '%LOOP_DETECTED%'"
    $traces = Count-Rows "SELECT COUNT(*) FROM artifacts WHERE kind='traces'"
    if ($spans -ge 5 -and $alerts -ge 1) { break }
    Start-Sleep -Milliseconds 500
}
Check 'spans arrived at the collector' ($spans -eq 5) "spans=$spans traces=$traces"
Check 'trace classified (LOOP_DETECTED alert)' ($alerts -ge 1) "loop alerts=$alerts"

# --- 4. collector DOWN --------------------------------------------------------------------------
Stop-Process -Id $collector.Id -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
$stillUp = $false
try { $stillUp = ((Invoke-WebRequest "$Url/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) } catch { }
Check 'collector is down' (-not $stillUp)
$clock = [Diagnostics.Stopwatch]::StartNew()
$runDown = Run $VenvPython @($ProgramPath, $Url)
$clock.Stop()
$resultDown = $null
foreach ($line in ($runDown.Out -split "`r?`n")) { if ($line.StartsWith('RESULT ')) { $resultDown = $line.Substring(7) | ConvertFrom-Json } }
Check 'program finished normally (collector down)' ($runDown.Code -eq 0 -and $null -ne $resultDown) $runDown.Out
if ($resultDown) {
    Check 'program result unchanged' ($resultDown.program_result -eq $resultUp.program_result) $resultDown.program_result
    Check 'drops are counted' ($resultDown.stats.exported -eq 0 -and $resultDown.stats.dropped_total -eq 5 -and $resultDown.stats.produced -eq 5) ($resultDown.stats | ConvertTo-Json -Compress)
    Check 'did not hang' ($clock.Elapsed.TotalSeconds -lt 30) ("{0:N1}s wall, {1}s in-process" -f $clock.Elapsed.TotalSeconds, $resultDown.elapsed_s)
    $Report['program_down'] = $resultDown
}

# --- 5. uninstall -------------------------------------------------------------------------------
$r = Run $VenvPython @('-m', 'pip', 'uninstall', '--yes', 'nexus-llmops')
Check 'pip uninstall' ($r.Code -eq 0) $r.Out
$r = Run $VenvPython @('-c', 'import nexus_llmops')
Check 'import fails after uninstall' ($r.Code -ne 0)
$r = Run $VenvPython @('-c', 'import nexus_agent')
Check 'alias import fails after uninstall' ($r.Code -ne 0)

$Report['finished'] = (Get-Date).ToString('o')
$Report['failed_checks'] = @($Failures)
$out = Join-Path $Repo "data\phase6\runs\scratch\smoke_$Source.json"
$Report | ConvertTo-Json -Depth 8 | Set-Content -Path $out -Encoding UTF8
if ($Failures.Count) { Say "SMOKE FAILED: $($Failures -join '; ')"; exit 1 }
Say "SMOKE PASSED ($Source $Version); report: $out"
exit 0
