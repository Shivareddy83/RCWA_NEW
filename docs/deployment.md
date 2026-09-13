# Deployment

Stage 13 uses four containers: PostgreSQL, FastAPI backend, the existing database-backed worker, and the Next.js production frontend. No Kafka, Redis, Celery, Kubernetes, or service mesh is required for this deployment.

## Prerequisites

- Docker Engine with Docker Compose v2.
- A copy of `.env.example` named `.env`.
- Strong, non-committed production secrets.

## First deployment

```sh
cp .env.example .env
# Edit .env and replace every secret placeholder.
docker compose build --no-cache
docker compose up -d
```

The backend entrypoint runs `alembic upgrade head` once for the backend service before starting Uvicorn. The worker uses the same backend image but sets `RUN_MIGRATIONS=0`, so it does not independently migrate the database.

## Verify

```sh
docker compose ps
docker compose logs --tail=100 backend worker frontend postgres
```

Then verify `/health`, `/ready`, `/docs`, `/openapi.json`, and `/metrics` on the backend and open the frontend at `http://localhost:3000`.

Docker execution is a required Stage 13 verification gate and was **not verified in the current execution environment because Docker is unavailable**.

## Seed data

For development only, after the database is ready, run the existing seed script from an environment that has the backend dependencies installed. Demo credentials and data are synthetic and must not be used as production credentials.

## Stop / restart

```sh
docker compose stop
docker compose start
docker compose restart worker
```

A worker restart is safe because jobs are durable and leased. An abruptly terminated worker leaves an expired lease for recovery rather than marking the job successful.

## Release identity

Set `RCAA_VERSION`, `BUILD_ID`, and `GIT_COMMIT_SHA` in the deployment environment. The backend exposes these non-secret values through `/version`.
