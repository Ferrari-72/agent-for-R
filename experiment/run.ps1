param(
    [ValidateRange(15, 15)][int]$Iterations = 15,
    [string]$ResumeRun,
    [switch]$ResumeDiscovery
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONHASHSEED = '0'
$env:TN_DEVELOP_SET = 'develop_v2.json'
$env:OPENEVOLVE_REQUEST_LIMIT = '100'
$env:TN_RESEARCH_ID = 'tensor-path-discovery-2026-10'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Path (Join-Path $project 'results') -Force | Out-Null
$env:OPENEVOLVE_REQUEST_BUDGET_DB = Join-Path $project 'results\model_request_budget_100.sqlite3'
$registration = Join-Path $project 'notes\formal_registration_2026-10.md'
$venvPython = Join-Path $project '.venv\Scripts\python.exe'
$framework = Join-Path (Split-Path -Parent $project) 'openevolve'
if (-not (Test-Path -LiteralPath (Join-Path $framework 'pyproject.toml'))) {
    throw "Vendored OpenEvolve source is missing: $framework"
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw 'Python environment is missing; run experiment\setup.ps1 once first'
}
if (-not (Test-Path -LiteralPath $registration)) {
    throw "Complete the preregistration before any model request: $registration"
}
$runManifestPath = Join-Path $project 'results\discovery_run_manifest.json'
$runFailures = Join-Path $project 'results\discovery_failures.jsonl'
$registrationHash = (& $venvPython -c "from hashlib import sha256; print(sha256(open(r'$registration','rb').read()).hexdigest())").Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not hash the formal registration' }
$frozenHashesJson = (& $venvPython -c "import json, sys; sys.path.insert(0, r'$project'); from tnlab.freeze import frozen_file_hashes; print(json.dumps(frozen_file_hashes(), sort_keys=True, separators=(',', ':')))").Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not compute frozen source hashes' }
$frozenHashes = $frozenHashesJson | ConvertFrom-Json
function Get-FrozenSourceHash {
    $hash = (& $venvPython -c "import json, sys; from hashlib import sha256; sys.path.insert(0, r'$project'); from tnlab.freeze import frozen_file_hashes; print(sha256(json.dumps(frozen_file_hashes(), sort_keys=True, separators=(',', ':')).encode()).hexdigest())").Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Could not hash frozen source manifest' }
    return $hash
}
$frozenHashesSha256 = Get-FrozenSourceHash
function Assert-FrozenSources {
    $currentJson = (& $venvPython -c "import json, sys; sys.path.insert(0, r'$project'); from tnlab.freeze import frozen_file_hashes; print(json.dumps(frozen_file_hashes(), sort_keys=True, separators=(',', ':')))" ).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Could not recheck frozen source hashes before model request' }
    if ($currentJson -cne $frozenHashesJson) {
        throw 'Frozen source or configuration changed during discovery orchestration'
    }
}
if ($ResumeRun -and -not $ResumeDiscovery) {
    $runManifestPath = $null
    $runFailures = $null
}
elseif ($ResumeDiscovery) {
    if (-not (Test-Path -LiteralPath $runManifestPath)) {
        throw 'Discovery resume requested but discovery_run_manifest.json is missing'
    }
    $runManifest = Get-Content -LiteralPath $runManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($runManifest.research_id -ne $env:TN_RESEARCH_ID) {
        throw 'Discovery manifest research ID differs from the current study'
    }
    if ($runManifest.registration_sha256 -ne $registrationHash) {
        throw 'Discovery manifest registration hash differs from the current registration'
    }
    if (-not $runManifest.frozen_source_hashes -or
        $runManifest.frozen_source_hashes_sha256 -ne $frozenHashesSha256) {
        throw 'Discovery manifest frozen source hashes differ from the current source'
    }
    $savedHashNames = @($runManifest.frozen_source_hashes.PSObject.Properties |
        ForEach-Object { $_.Name })
    $currentHashNames = @($frozenHashes.PSObject.Properties |
        ForEach-Object { $_.Name })
    if ($savedHashNames.Count -ne $currentHashNames.Count) {
        throw 'Discovery manifest frozen source file set differs from the current source'
    }
    foreach ($property in $frozenHashes.PSObject.Properties) {
        if ($runManifest.frozen_source_hashes.($property.Name) -cne $property.Value) {
            throw "Discovery manifest frozen hash differs for $($property.Name)"
        }
    }
    if ($runManifest.run_ids.Count -ne 5 -or $runManifest.runs.Count -ne 5 -or
        (@($runManifest.runs | ForEach-Object { $_.run_id } | Select-Object -Unique).Count -ne 5)) {
        throw 'Discovery manifest does not preserve exactly five unique run identities'
    }
}
else {
    if (Test-Path -LiteralPath $runManifestPath) {
        throw 'Discovery run manifest already exists; use -ResumeDiscovery to continue its fixed identities'
    }
    $discoveryRunIds = @()
    for ($runIndex = 1; $runIndex -le 5; $runIndex++) {
        $discoveryRunIds += [guid]::NewGuid().ToString()
    }
    $runManifest = [ordered]@{
        research_id = $env:TN_RESEARCH_ID
        created_at = [DateTime]::UtcNow.ToString('o')
        registration_sha256 = $registrationHash
        frozen_source_hashes = $frozenHashes
        frozen_source_hashes_sha256 = $frozenHashesSha256
        run_ids = $discoveryRunIds
        model = $null
        calibration_run_id = ('calibration-' + [guid]::NewGuid().ToString())
        calibration_status = 'pending'
        calibration_directory = (Join-Path $project ('results\calibration_' + [guid]::NewGuid().ToString()))
        runs = @(
            [ordered]@{run_id = $discoveryRunIds[0]; status = 'pending'},
            [ordered]@{run_id = $discoveryRunIds[1]; status = 'pending'},
            [ordered]@{run_id = $discoveryRunIds[2]; status = 'pending'},
            [ordered]@{run_id = $discoveryRunIds[3]; status = 'pending'},
            [ordered]@{run_id = $discoveryRunIds[4]; status = 'pending'}
        )
    }
    ($runManifest | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath $runManifestPath -Encoding UTF8
}
if (-not $env:OPENAI_API_KEY) {
    $secretFile = Join-Path $project '.secrets\siliconflow-key.dpapi'
    if (Test-Path -LiteralPath $secretFile) {
        $encrypted = [System.IO.File]::ReadAllText($secretFile, [System.Text.Encoding]::UTF8)
        $secure = ConvertTo-SecureString -String $encrypted
    }
    else {
        $secure = Read-Host 'SiliconFlow API Key (input hidden)' -AsSecureString
    }
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}
if (-not $env:OPENAI_API_KEY) { throw 'API Key was not entered' }

Push-Location $project
try {
    & $venvPython -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed' }
    docker info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Engine is required for a formal experiment' }
    $sourceHash = (& $venvPython -c 'from tnlab.freeze import image_source_hash; print(image_source_hash())').Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Could not hash runner source' }
    $imageInfo = (docker image inspect tnlab-runner:py313-v1 | ConvertFrom-Json)
    if ($LASTEXITCODE -ne 0 -or -not $imageInfo) { throw 'Runner image is missing; run experiment\setup.ps1 first' }
    $imageHash = $imageInfo[0].Config.Labels.'org.tnlab.source-sha256'
    if ($LASTEXITCODE -ne 0 -or $imageHash -ne $sourceHash) {
        throw 'Runner image is missing or stale; run experiment\setup.ps1 first'
    }
    & $venvPython -c "from openevolve.utils.request_budget import initialize_request_budget; initialize_request_budget(r'$env:OPENEVOLVE_REQUEST_BUDGET_DB', '$env:TN_RESEARCH_ID', 100)"
    if ($LASTEXITCODE -ne 0) { throw 'Could not initialize or verify the new 100-request research ledger' }
    if ($ResumeRun) {
        $resumePath = (Resolve-Path -LiteralPath $ResumeRun).Path
        $runIdFile = Join-Path $resumePath 'run_id.txt'
        if (-not (Test-Path -LiteralPath $runIdFile)) { throw 'Resume run is missing run_id.txt' }
        $env:TN_RUN_ID = [System.IO.File]::ReadAllText($runIdFile, [System.Text.Encoding]::UTF8).Trim()
        $env:TN_EXECUTION_MODE = 'container'
        $reportPath = Join-Path $resumePath 'development_report.json'
        if (Test-Path -LiteralPath $reportPath) { throw 'Completed run cannot be resumed' }
        $env:TN_RUN_REQUEST_START_ID = '0'
        $requestState = (& $venvPython -c "from openevolve.utils.request_budget import request_usage; import os; total=request_usage()['total']; own=request_usage(run_id=os.environ['TN_RUN_ID'])['total']; print(f'{total-own},{total}')").Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Could not read resumed run request attribution' }
        $requestCounts = $requestState.Split(',')
        $env:TN_RUN_REQUEST_COUNT_BEFORE = $requestCounts[0]
        $env:TN_MODEL = 'deepseek-ai/DeepSeek-V3.2'
        & $venvPython run_experiment.py --iterations $Iterations --resume-run $resumePath
        if ($LASTEXITCODE -ne 0) { throw 'Experiment resume failed' }
        return
    }

    if ($runManifest.calibration_status -eq 'failed') {
        throw "Calibration failed under the preregistered one-shot rule: $($runManifest.calibration_error)"
    }
    elseif ($runManifest.calibration_status -eq 'requesting') {
        throw 'Calibration was interrupted after request processing began; automatic retry is forbidden'
    }
    elseif ($runManifest.calibration_status -eq 'completed') {
        if (-not $runManifest.model) { throw 'Completed calibration is missing its selected model' }
        $env:TN_MODEL = [string]$runManifest.model
    }
    elseif ($runManifest.calibration_status -eq 'pending') {
        Assert-FrozenSources
        $env:TN_RUN_ID = [string]$runManifest.calibration_run_id
        $env:TN_EXECUTION_MODE = 'container'
        $env:TN_RUN_REQUEST_START_ID = (& $venvPython -c 'from openevolve.utils.request_budget import request_last_id; print(request_last_id())').Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Could not read model request budget position' }
        $env:TN_RUN_REQUEST_COUNT_BEFORE = (& $venvPython -c 'from openevolve.utils.request_budget import request_usage; print(request_usage()["total"])').Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Could not read cumulative model request count' }
        $runManifest.calibration_status = 'requesting'
        ($runManifest | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $runManifestPath -Encoding UTF8
        try {
            $selectedModel = & $venvPython probe_api.py
            if ($LASTEXITCODE -ne 0) { throw 'API probe failed' }
            $env:TN_MODEL = $selectedModel.Trim()
            Write-Host "Selected model: $env:TN_MODEL"
            Assert-FrozenSources
            $calibrationDir = [string]$runManifest.calibration_directory
            & $venvPython calibrate_api.py --model $env:TN_MODEL --output $calibrationDir
            if ($LASTEXITCODE -ne 0) { throw 'Machine-checkable calibration failed; discovery was not started' }
            $runManifest.model = $env:TN_MODEL
            $runManifest.calibration_status = 'completed'
            ($runManifest | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $runManifestPath -Encoding UTF8
        }
        catch {
            $runManifest.calibration_status = 'failed'
            $runManifest.calibration_error = $_.Exception.Message
            ($runManifest | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $runManifestPath -Encoding UTF8
            throw
        }
    }
    else {
        throw "Calibration status '$($runManifest.calibration_status)' is terminal or invalid; calibration cannot be retried"
    }

    $discoveryRunIds = @($runManifest.run_ids)
    for ($runIndex = 1; $runIndex -le 5; $runIndex++) {
        Assert-FrozenSources
        $entry = $runManifest.runs[$runIndex - 1]
        if ($entry.status -eq 'completed') { continue }
        if ($entry.status -notin @('pending', 'failed', 'running')) {
            throw "Unknown discovery run status at index ${runIndex}: $($entry.status)"
        }
        $env:TN_RUN_ID = [string]$entry.run_id
        $env:TN_EXECUTION_MODE = 'container'
        $env:TN_MODEL = [string]$runManifest.model
        $matchingRuns = @(Get-ChildItem -LiteralPath (Join-Path $project 'results') -Directory -Filter 'evolve_*' |
            Where-Object {
                $idFile = Join-Path $_.FullName 'run_id.txt'
                (Test-Path -LiteralPath $idFile) -and
                ([System.IO.File]::ReadAllText($idFile).Trim() -eq $env:TN_RUN_ID)
            })
        if ($matchingRuns.Count -gt 1) {
            throw "Multiple run directories already use fixed run ID $env:TN_RUN_ID; manual audit is required"
        }
        $resumePath = $null
        if ($matchingRuns.Count -eq 1) {
            $existingPath = $matchingRuns[0].FullName
            $reportPath = Join-Path $existingPath 'development_report.json'
            if (Test-Path -LiteralPath $reportPath) {
                $runManifest.runs[$runIndex - 1] = [ordered]@{
                    run_id = $env:TN_RUN_ID
                    directory = $existingPath
                    status = 'completed'
                }
                ($runManifest | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $runManifestPath -Encoding UTF8
                continue
            }
            $checkpointPath = Join-Path $existingPath 'checkpoints'
            if (Test-Path -LiteralPath $checkpointPath) {
                $resumePath = $existingPath
            }
            else {
                throw "Fixed run ID $env:TN_RUN_ID has an incomplete directory without a checkpoint"
            }
        }
        $env:TN_RUN_REQUEST_START_ID = (& $venvPython -c 'from openevolve.utils.request_budget import request_last_id; print(request_last_id())').Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Could not read model request budget position' }
        $env:TN_RUN_REQUEST_COUNT_BEFORE = (& $venvPython -c 'from openevolve.utils.request_budget import request_usage; print(request_usage()["total"])').Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Could not read cumulative model request count' }
        $runManifest.runs[$runIndex - 1].status = 'running'
        ($runManifest | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $runManifestPath -Encoding UTF8
        Write-Host "Starting discovery run $runIndex/5 ($env:TN_RUN_ID)"
        try {
            if ($resumePath) {
                & $venvPython run_experiment.py --iterations $Iterations --resume-run $resumePath
            }
            else {
                & $venvPython run_experiment.py --iterations $Iterations
            }
            if ($LASTEXITCODE -ne 0) { throw "run_experiment exit code $LASTEXITCODE" }
            $completed = @(Get-ChildItem -LiteralPath (Join-Path $project 'results') -Directory -Filter 'evolve_*' |
                Where-Object {
                    $idFile = Join-Path $_.FullName 'run_id.txt'
                    (Test-Path -LiteralPath $idFile) -and
                    ([System.IO.File]::ReadAllText($idFile).Trim() -eq $env:TN_RUN_ID)
                } | Sort-Object LastWriteTime -Descending)
            if ($completed.Count -ne 1) { throw "Could not uniquely locate completed run for $env:TN_RUN_ID" }
            $runManifest.runs[$runIndex - 1] = [ordered]@{
                run_id = $env:TN_RUN_ID
                directory = $completed[0].FullName
                status = 'completed'
            }
            ($runManifest | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $runManifestPath -Encoding UTF8
        }
        catch {
            $runManifest.runs[$runIndex - 1].status = 'failed'
            $runManifest.runs[$runIndex - 1].error = $_.Exception.Message
            if ($resumePath) { $runManifest.runs[$runIndex - 1].directory = $resumePath }
            Add-Content -LiteralPath $runFailures -Value (
                ([ordered]@{run_id = $env:TN_RUN_ID; run_index = $runIndex;
                            error = $_.Exception.Message; timestamp = [DateTime]::UtcNow.ToString('o')} |
                    ConvertTo-Json -Compress)) -Encoding UTF8
            ($runManifest | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $runManifestPath -Encoding UTF8
            Write-Warning "Discovery run $runIndex failed; evidence was retained and the next independent run will start"
        }
    }
    $selectionRuns = @($runManifest.runs |
        Where-Object { $_.status -eq 'completed' } |
        ForEach-Object { $_.directory })
    if ($selectionRuns.Count -ne 5) {
        throw "Formal discovery requires exactly five completed run directories; found $($selectionRuns.Count)"
    }
    ($runManifest | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath $runManifestPath -Encoding UTF8
    & $venvPython select_discovery.py --run-manifest $runManifestPath --output (Join-Path $project 'results\discovery_selection.json')
    if ($LASTEXITCODE -ne 0) { throw 'Discovery selection was inconclusive; final evaluation was not started' }
    Write-Host "Discovery selection complete: results\discovery_selection.json"
}
finally { Pop-Location }
