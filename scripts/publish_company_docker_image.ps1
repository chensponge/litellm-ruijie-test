param(
    [string]$SourceImage = "litellm-docker-database:local",
    [string]$TargetImage,
    [switch]$Push,
    [switch]$DeployLocal,
    [string]$ComposeFile = "docker-compose.company-db.yml"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $TargetImage) {
    throw "TargetImage is required, for example registry.example.com/litellm/litellm-docker-database:v1"
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "Tagging $SourceImage as $TargetImage"
docker tag $SourceImage $TargetImage

if ($Push) {
    Write-Host "Pushing $TargetImage"
    docker push $TargetImage
}

if ($DeployLocal) {
    Write-Host "Deploying local stack with image $TargetImage"
    $env:LITELLM_IMAGE = $TargetImage
    docker compose -f $ComposeFile up -d --no-build
}

Write-Host "Prepared image: $TargetImage"