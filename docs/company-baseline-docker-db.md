# Company Baseline Docker DB

This repository is the clean company baseline built from official LiteLLM source.

Goal:
- keep upstream code close to official
- build LiteLLM from source instead of depending on upstream runtime images
- run LiteLLM and PostgreSQL together with one compose file

Files added or updated for the baseline:
- `docker-compose.company-db.yml`
- `docker/Dockerfile.database`
- `.env.company`
- `.env.company.example`
- `.env.company.local.example`
- `config.company-baseline.yaml`
- `scripts/build_company_docker_image.ps1`
- `scripts/publish_company_docker_image.ps1`

Build target alignment:
- the compose file builds from local source with `docker/Dockerfile.database`
- the resulting local image name matches the upstream docker-database naming pattern: `litellm-docker-database:*`

## What was intentionally carried over

- provider env structure from the previous internal repo
- baseline proxy config shape
- PostgreSQL-backed startup mode
- one starter model entry for company validation
- Langfuse callback config surfaces through environment variables

## What was intentionally not carried over

- auth bypasses
- Feishu externalization experiments
- UI local dev patches
- old proxy core modifications
- company business logic

## First-run steps

1. Fill provider keys in `.env.company`
2. If needed, update `config.company-baseline.yaml`
3. Run:

```powershell
docker compose -f docker-compose.company-db.yml up --build
```

## Delivery Steps

From the repository side, the remaining delivery path is now only three steps:

1. Build the self-compiled image from local source.
2. Optionally tag and push it to your registry.
3. Deploy with the same compose file, either from the local image or a pushed image.

Build locally:

```powershell
.\scripts\build_company_docker_image.ps1 -ImageTag v1
```

Build and export a tar archive for offline delivery:

```powershell
.\scripts\build_company_docker_image.ps1 -ImageTag v1 -SaveTarPath .\dist\litellm-docker-database-v1.tar
```

Tag and push to a registry:

```powershell
.\scripts\publish_company_docker_image.ps1 \
	-SourceImage litellm-docker-database:v1 \
	-TargetImage registry.example.com/litellm/litellm-docker-database:v1 \
	-Push
```

Deploy locally from a prebuilt image without rebuilding:

```powershell
.\scripts\publish_company_docker_image.ps1 \
	-SourceImage litellm-docker-database:v1 \
	-TargetImage registry.example.com/litellm/litellm-docker-database:v1 \
	-DeployLocal
```

Notes:
- `docker-compose.company-db.yml` now accepts `LITELLM_IMAGE`; default remains `litellm-docker-database:local`
- when Docker is healthy, `docker compose -f docker-compose.company-db.yml up --build` is still the fastest local verification path
- the current blocker in your environment is the Windows VM / Docker backend, not a missing Dockerfile step in this repository

## CI Build Path

This repository already has a GitHub remote, so you can use GitHub Actions as your build machine even when local Docker is blocked.

Workflow:
- `.github/workflows/build-company-docker-image.yml`

How to use it:
1. Push your branch to GitHub.
2. Open the GitHub Actions tab.
3. Run `Build Company Docker Image` manually.
4. Choose either:
	- `push_to_ghcr = false` to get a downloadable tar artifact
	- `push_to_ghcr = true` to push to `ghcr.io/<owner>/litellm-docker-database:<tag>`

This is the best workaround when the local Windows VM cannot run Docker Desktop or WSL 2.

## Local Run Without Virtualenv

If Docker is unavailable and you only need a local config smoke test, run LiteLLM directly from the host Python environment.

1. Install project dependencies into your current Python environment.
2. Load values from `.env.company`.
3. Start LiteLLM with the company baseline config:

```powershell
pip install -e .
Get-Content .env.company | ForEach-Object {
	if ($_ -match '^(?!#)([^=]+)="?(.*)"?$') {
		[System.Environment]::SetEnvironmentVariable($matches[1], $matches[2])
	}
}
litellm --config ./config.company-baseline.yaml --port 4000
```

Notes:
- `.env.company` now represents the company deployment baseline, including the company PostgreSQL URL
- for local-only testing, copy `.env.company.local.example` to `.env.company.local` and set `DATABASE_URL=""`
- `docker-compose.company-db.yml` ignores `.env.company`'s company database URL unless you explicitly set `DATABASE_URL_DOCKER`; by default it uses the bundled local `db` container
- for host-run smoke tests, either load `.env.company.local` or override `DATABASE_URL` to an empty string before starting LiteLLM
- Feishu alerting from the old internal repo is not enabled by default in this baseline, because an empty webhook crashes current upstream startup; enable it only when you have a real webhook and want to carry that customization explicitly
- this host-run path is only for local verification and does not replace the docker-database delivery target

## Success criteria

- image builds from local source
- postgres starts successfully
- LiteLLM connects to postgres
- `http://localhost:4000/health/liveliness` returns healthy
- dashboard can be opened on port 4000

## Next step after baseline is stable

Add company customizations only through:
- external services
- UI overlay or separate frontend
- minimal documented platform patches
