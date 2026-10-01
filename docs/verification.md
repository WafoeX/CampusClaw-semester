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

---

## Knowledge retrieval verification summary

The end-to-end verification for `add-class-scoped-knowledge-retrieval` was run on 2026-09-30. Every Docker run used a fresh Compose project, temporary volumes, generated credentials, and a deterministic private fake embedding endpoint; no live or paid provider was contacted. Temporary projects and volumes were removed after each run.

### Backend format, lint, type, unit, and coverage

```sh
cd api
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest -q
```

Result: all static checks passed; **81 passed, 4 skipped**; branch coverage **80.25%** (required 80%). The skipped tests are the separately executed PostgreSQL integration cases.

```sh
cd api
TEST_DATABASE_URL="$TEMP_POSTGRES_URL" \
  uv run pytest --no-cov -q -m integration tests/test_api_postgres_integration.py
```

Result: **3 passed** against a temporary PostgreSQL 16 container. The fixture created `pg_trgm` and used an isolated `test_api_*` schema with `public` on its search path.

### PostgreSQL and Alembic

```sh
cd api
DATABASE_URL="$TEMP_POSTGRES_URL" uv run alembic upgrade head
DATABASE_URL="$TEMP_POSTGRES_URL" uv run alembic current
DATABASE_URL="$TEMP_POSTGRES_URL" uv run alembic downgrade -1
DATABASE_URL="$TEMP_POSTGRES_URL" uv run alembic upgrade head
uv run alembic heads
uv run alembic history
uv run pytest --no-cov -q tests/test_migration_shape.py
```

Result: fresh upgrade reached `20260929_0003 (head)`; one-step downgrade and re-upgrade passed; the graph had one head; migration shape test **1 passed**.

### Frontend lint, type, unit, build, and browser acceptance

```sh
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
PLAYWRIGHT_BASE_URL="$TEMP_GATEWAY_URL" npm run test:e2e
```

Result: lint and type checks passed; **10 unit tests passed**; production build passed; **5 Playwright tests passed** through the published gateway. Coverage includes authentication, class isolation, upload/download, independent knowledge requests, citation focus navigation, and generic invalid credentials.

### Docker, Compose, Qdrant reconciliation, snapshot, and rebuild

```sh
docker compose -p "$PROJECT" build api web
docker compose -p "$PROJECT" up -d db qdrant migrate seed api web
docker compose -p "$PROJECT" run --rm --no-deps api campusclaw backfill
docker compose -p "$PROJECT" run --rm --no-deps api campusclaw indexer --max-jobs 10
docker compose -p "$PROJECT" run --rm --no-deps api \
  campusclaw reconcile-vectors --class-id "$ALPHA_CLASS_ID"
docker compose -p "$PROJECT" run --rm --no-deps api campusclaw qdrant-snapshot
docker compose -p "$PROJECT" run --rm --no-deps api campusclaw vector-rebuild
python tests/test_compose_ports.py
curl -fsS "$TEMP_GATEWAY_URL/health"
```

Before reconciliation, the acceptance harness inserted one same-class orphan point. Result: reconciliation reported `deleted=1`; the Qdrant snapshot completed; after deleting the collection, `vector-rebuild` recreated it and rebuilt **2 vectors**; post-rebuild reconciliation for both classes reported `missing=0 orphaned=0 repaired=0`. Runtime port inspection found only the Web gateway published. Health returned HTTP 200 with retrieval ready and generation safely degraded.

```sh
api/.venv/bin/python -m pytest -q tests
bash tests/check-no-secrets.sh
docker compose config --format json
```

Result: root deployment/documentation suite **5 passed**; the production frontend bundle contained no server-only markers; rendered Compose included internal-only PostgreSQL, Qdrant, API, and indexer services.

### Backup, restore, and production defaults

```sh
api/.venv/bin/python tests/check_backup_restore.py
api/.venv/bin/python tests/check_production_seed.py
```

Result: coordinated PostgreSQL/material backup and restore preserved accounts, material metadata, file SHA-256 values, the active retrieval version, and `knowledge_chunks`; production remained empty by default and seeded only after explicit opt-in. Qdrant recovery was verified separately by the delete-and-rebuild sequence above because vectors are derived data.

### OpenSpec

```sh
openspec validate --changes --strict
```

Result: **3 passed, 0 failed**.

### Bugs found and fixed during the gate

- Semantic retry now reuses the active PostgreSQL version and original chunk IDs instead of creating duplicate versions/chunks.
- Qdrant reconciliation now consumes every scroll page, reports incompatible points as missing, and deletes only selected stale/orphan points.
- `vector-rebuild` now creates an absent collection before upsert; reconciliation repairs missing vectors in configured batches.
- PostgreSQL integration fixtures now install `pg_trgm` and include `public` in isolated-schema search paths.
- Source-card downloads now use authenticated Bearer fetches rather than unauthenticated browser navigation, and inline citations move keyboard focus to their source card.
