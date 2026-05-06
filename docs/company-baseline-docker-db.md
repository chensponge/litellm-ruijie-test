# Company Baseline Docker DB

This repository is the clean company baseline built from official LiteLLM source.

Goal:
- keep upstream code close to official
- build LiteLLM from source instead of depending on upstream runtime images
- run LiteLLM and PostgreSQL together with one compose file

Files added for the baseline:
- `docker-compose.company-db.yml`
- `docker/Dockerfile.company-base`
- `.env.company`
- `.env.company.example`
- `config.company-baseline.yaml`

## What was intentionally carried over

- provider env structure from the previous internal repo
- baseline proxy config shape
- PostgreSQL-backed startup mode
- one starter model entry for company validation

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
