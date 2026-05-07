param(
    [switch]$UseCompanyDatabase,
    [int]$Port = 4000
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

if (-not $UseCompanyDatabase) {
    Set-Item -Path Env:DATABASE_URL -Value ""
}

litellm --config ./config.company-baseline.yaml --port $Port