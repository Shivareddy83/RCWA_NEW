# Docker Architecture

## Images

### Backend

`backend/Dockerfile` uses Python 3.12 slim, installs backend dependencies without a pip cache, copies only the backend build context, runs as UID/GID 10001, and uses an entrypoint that performs the migration step before `exec`-ing Uvicorn. Runtime secrets are supplied by the container environment rather than baked into image layers.

### Frontend

`frontend/Dockerfile` uses three stages: dependency installation, Next.js build, and a small Node 22 Alpine runtime. The Next.js standalone output is copied into the runtime image. The runtime runs as UID/GID 10001 and starts `server.js`, not the development server.

`NEXT_PUBLIC_API_URL` is public browser configuration and is supplied as a build argument. Backend secrets are never passed to the frontend build.

## Build contexts

Each service has a `.dockerignore` excluding source-control metadata, environment secrets, caches, local databases, `node_modules`, `.next`, test artifacts, and logs.

## Verification

Required commands:

```sh
docker compose build --no-cache
docker compose config
docker compose up -d
```

Image inspection should confirm non-root runtime users and absence of `.env`, private keys, local database files, and test artifacts.

These Docker checks are **not verified in the current execution environment because the Docker CLI is unavailable**.
