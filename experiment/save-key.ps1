$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$secretDir = Join-Path $project '.secrets'
$secretFile = Join-Path $secretDir 'siliconflow-key.dpapi'
New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
$secure = Read-Host 'SiliconFlow API Key (input hidden)' -AsSecureString
if ($secure.Length -eq 0) { throw 'API Key was not entered' }
$encrypted = ConvertFrom-SecureString -SecureString $secure
[System.IO.File]::WriteAllText($secretFile, $encrypted, [System.Text.Encoding]::UTF8)
Write-Host "Encrypted key saved for this Windows account: $secretFile"
