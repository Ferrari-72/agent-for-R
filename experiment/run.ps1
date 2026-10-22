param([ValidateRange(1, 20)][int]$Iterations = 3)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONHASHSEED = '0'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $project '.venv\Scripts\python.exe'
$framework = Join-Path (Split-Path -Parent $project) 'openevolve'
$patch = Join-Path $project 'patches\openevolve.patch'
$upstreamCommit = '15441c04bc5906790b343e0ff103d33935c33c71'
if (-not (Test-Path -LiteralPath (Join-Path $framework 'pyproject.toml'))) {
    if (Test-Path -LiteralPath $framework) {
        throw "OpenEvolve directory exists but is incomplete: $framework"
    }
    git clone https://github.com/algorithmicsuperintelligence/openevolve.git $framework
    if ($LASTEXITCODE -ne 0) { throw 'Could not download OpenEvolve' }
    git -C $framework checkout $upstreamCommit
    if ($LASTEXITCODE -ne 0) { throw 'Could not select pinned OpenEvolve commit' }
    git -C $framework apply $patch
    if ($LASTEXITCODE -ne 0) { throw 'Could not apply OpenEvolve patch' }
}
git -C $framework apply --reverse --check $patch 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "OpenEvolve patch is missing or differs from this project: $framework"
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    $env:UV_CACHE_DIR = Join-Path (Split-Path -Parent $project) '.uv-cache'
    uv venv (Join-Path $project '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment' }
}
uv pip install --python $venvPython -r (Join-Path $project 'requirements.txt') -e $framework
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }

if (-not $env:OPENAI_API_KEY) {
    $secure = Read-Host 'SiliconFlow API Key (input hidden)' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}
if (-not $env:OPENAI_API_KEY) { throw 'API Key was not entered' }

Push-Location $project
try {
    & $venvPython -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed' }
    $selectedModel = & $venvPython probe_api.py
    if ($LASTEXITCODE -ne 0) { throw 'API probe failed' }
    $env:TN_MODEL = $selectedModel.Trim()
    Write-Host "Selected model: $env:TN_MODEL"
    & $venvPython run_minimal.py --iterations $Iterations
    if ($LASTEXITCODE -ne 0) { throw 'Experiment failed' }
}
finally { Pop-Location }
