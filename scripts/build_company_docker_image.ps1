param(
    [string]$ImageName = "litellm-docker-database",
    [string]$ImageTag = "local",
    [string]$Dockerfile = "docker/Dockerfile.database",
    [string]$Context = ".",
    [string]$Platform = "",
    [string]$SaveTarPath = "",
    [switch]$NoCache,
    [switch]$Pull
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$imageRef = "${ImageName}:${ImageTag}"
$arguments = @("build", "-f", $Dockerfile, "-t", $imageRef)

if ($Pull) {
    $arguments += "--pull"
}

if ($NoCache) {
    $arguments += "--no-cache"
}

if ($Platform) {
    $arguments += @("--platform", $Platform)
}

$arguments += $Context

Write-Host "Building image $imageRef from $Dockerfile"
docker @arguments

Write-Host "Verifying image $imageRef"
docker image inspect $imageRef | Out-Null

if ($SaveTarPath) {
    $savePath = Resolve-Path -Path (Split-Path -Parent $SaveTarPath) -ErrorAction SilentlyContinue
    if (-not $savePath) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $SaveTarPath) | Out-Null
    }
    Write-Host "Saving image archive to $SaveTarPath"
    docker save -o $SaveTarPath $imageRef
}

Write-Host "Built image: $imageRef"