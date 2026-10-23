$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$framework = Join-Path (Split-Path -Parent $project) 'openevolve'
$venvPython = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath (Join-Path $framework 'pyproject.toml'))) {
    throw "Vendored OpenEvolve source is missing: $framework"
}
Push-Location $project
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        uv venv --python 3.13 (Join-Path $project '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment' }
    }
    uv pip sync --python $venvPython (Join-Path $project 'requirements.lock')
    if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed' }
    uv pip install --python $venvPython --no-deps -e $framework
    if ($LASTEXITCODE -ne 0) { throw 'Vendored OpenEvolve installation failed' }
    docker info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Engine is required to build the runner image' }
    $sourceHash = (& $venvPython -c 'from tnlab.freeze import image_source_hash; print(image_source_hash())').Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Could not hash runner source' }
    docker build -f (Join-Path $project 'Dockerfile.runner') -t tnlab-runner:py313-v1 --build-arg "SOURCE_HASH=$sourceHash" $project
    if ($LASTEXITCODE -ne 0) { throw 'Candidate runner image build failed' }
    $immutableTag = 'tnlab-runner:sha-' + $sourceHash.Substring(0, 12)
    docker tag tnlab-runner:py313-v1 $immutableTag
    if ($LASTEXITCODE -ne 0) { throw 'Could not retain the source-specific runner image' }
    Write-Host "Environment ready. Runner source hash: $sourceHash"
    Write-Host "Retained runner image: $immutableTag"
}
finally { Pop-Location }
