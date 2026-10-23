param([ValidateRange(1, 20)][int]$Iterations = 10)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONHASHSEED = '0'
$env:TN_DEVELOP_SET = 'develop_v2.json'
$env:OPENEVOLVE_REQUEST_LIMIT = '30'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Path (Join-Path $project 'results') -Force | Out-Null
$env:OPENEVOLVE_REQUEST_BUDGET_DB = Join-Path $project 'results\model_request_budget.sqlite3'
$venvPython = Join-Path $project '.venv\Scripts\python.exe'
$framework = Join-Path (Split-Path -Parent $project) 'openevolve'
if (-not (Test-Path -LiteralPath (Join-Path $framework 'pyproject.toml'))) {
    throw "Vendored OpenEvolve source is missing: $framework"
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw 'Python environment is missing; run experiment\setup.ps1 once first'
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
    $env:TN_EXECUTION_MODE = 'container'
    $env:TN_RUN_ID = [guid]::NewGuid().ToString()
    $env:TN_RUN_REQUEST_START_ID = (& $venvPython -c 'from openevolve.utils.request_budget import request_last_id; print(request_last_id())').Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Could not read model request budget position' }
    $env:TN_RUN_REQUEST_COUNT_BEFORE = (& $venvPython -c 'from openevolve.utils.request_budget import request_usage; print(request_usage()["total"])').Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Could not read cumulative model request count' }
    $selectedModel = & $venvPython probe_api.py
    if ($LASTEXITCODE -ne 0) { throw 'API probe failed' }
    $env:TN_MODEL = $selectedModel.Trim()
    Write-Host "Selected model: $env:TN_MODEL"
    & $venvPython run_experiment.py --iterations $Iterations
    if ($LASTEXITCODE -ne 0) { throw 'Experiment failed' }
}
finally { Pop-Location }
