param(
    [int]$Port = 4000,
    [string]$DatabaseUrl = "postgresql://postgres:123456@127.0.0.1:5432/litellm"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

foreach ($envFile in @(".env.company", ".env.company.local")) {
    if (-not (Test-Path $envFile)) {
        continue
    }

    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim().Trim('"')
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

$schemaPath = Join-Path $repoRoot "litellm\proxy\schema.prisma"
$localSchemaPath = Join-Path $repoRoot "litellm\proxy\schema.local.prisma"

$localSchemaContents = (Get-Content $schemaPath -Raw) -replace 'binaryTargets = \[.*\]', 'binaryTargets = ["native"]'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($localSchemaPath, $localSchemaContents, $utf8NoBom)

Set-Item -Path Env:DATABASE_URL -Value $DatabaseUrl
python -m prisma generate --schema $localSchemaPath | Out-Host

$prismaPackagePath = python -c "import os, prisma; print(os.path.dirname(prisma.__file__))"
if (-not $prismaPackagePath) {
    throw "Unable to locate installed prisma package path."
}

$prismaPackagePath = $prismaPackagePath.Trim()
Copy-Item $localSchemaPath (Join-Path $prismaPackagePath "schema.prisma") -Force

litellm --config ./config.company-baseline.yaml --port $Port