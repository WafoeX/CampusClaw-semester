# Verification summary

The end-to-end verification for the `add-class-isolated-material-library` change was run on 2026-09-23.
Secrets and sample passwords were generated in a mode-0600 temporary environment file and are not recorded here.

## Backend

```sh
cd api
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest -q
```

Result: formatting, lint, and type checks passed; **53 passed, 5 skipped**; coverage **88.26%** (required 80%).

The PostgreSQL-backed integration suite was also run against a temporary PostgreSQL 16 container:

```sh
cd api
TEST_DATABASE_URL="$TEST_DATABASE_URL" uv run pytest --no-cov -q -m integration tests/test_api_postgres_integration.py
```

Result: **3 passed**.

## Frontend

```sh
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

Result: lint and type checks passed; **8 unit tests passed**; production build passed.

## Containers and Compose

```sh
docker pull python:3.12-slim
docker pull node:22-alpine
docker pull nginx:1.29-alpine
docker pull ghcr.io/astral-sh/uv:0.12.16
docker compose --env-file "$ACCEPTANCE_ENV" -p campusclaw_acceptance build api web
docker compose --env-file "$ACCEPTANCE_ENV" -p campusclaw_acceptance up -d --force-recreate db migrate seed api web
```

Result: all base images pulled; API and web images built; migration and seed completed; API became healthy; `/health` through the published web gateway returned HTTP 200.

Port and production-seed acceptance:

```sh
python tests/test_compose_ports.py
python tests/check_production_seed.py
uv run pytest -q tests/test_compose_config.py tests/test_compose_ports.py
```

Result: running stack exposed only the web gateway; port mutation checks passed; production empty-volume seed-disabled and explicit seed-enabled checks passed; **2 static acceptance tests passed**.

## Browser acceptance

```sh
cd frontend
PLAYWRIGHT_BASE_URL=http://127.0.0.1:18080 npm run test:e2e
```

Result: **4 passed** through the published web gateway only:

- unauthenticated protected-page redirect;
- teacher login, upload, list, download, and logout;
- beta student class isolation and no upload control;
- generic invalid-credential error.

## OpenSpec

```sh
openspec validate --changes --strict
```

Result: **1 passed, 0 failed**.
