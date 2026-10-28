$ErrorActionPreference = 'Stop'

$projectPath = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$projectName = Split-Path -Leaf $projectPath
$backupParent = Split-Path -Parent $projectPath
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$archivePath = Join-Path $backupParent "$projectName-backup-$timestamp.zip"
$stagingPath = Join-Path $env:TEMP "$projectName-backup-$timestamp"

try {
    New-Item -ItemType Directory -Path $stagingPath -Force | Out-Null

    & robocopy $projectPath $stagingPath /E `
        /XD (Join-Path $projectPath '.venv') (Join-Path $projectPath '__pycache__') (Join-Path $projectPath '.git') `
        /XF '.env' 'secrets.toml' /NFL /NDL /NJH /NJS /NC /NS | Out-Null

    if ($LASTEXITCODE -ge 8) {
        throw "La copie de sauvegarde a échoué (code robocopy $LASTEXITCODE)."
    }

    Compress-Archive -Path (Join-Path $stagingPath '*') -DestinationPath $archivePath -CompressionLevel Optimal
    Write-Output "Sauvegarde créée : $archivePath"
}
finally {
    if (Test-Path -LiteralPath $stagingPath) {
        Remove-Item -LiteralPath $stagingPath -Recurse -Force
    }
}