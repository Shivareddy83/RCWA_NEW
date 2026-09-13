# Automation Upgrade — What Changed

Scope requested: (1) get CI fully green, (2) add CD, (3) add security-scan
automation, (4) full DevOps pass. Done in that order, with one honest caveat
up front.

## Environment caveat (read this first)
This sandbox has no network/package access, so I could not `pip install` or
`npm ci` the real dependencies or actually execute `pytest`/`npm test` here.
Everything below that is a **new YAML/config file** is verified for syntax
(`yaml.safe_load`) and cross-checked against your existing scripts and
`package.json`. Anything claiming "fixed and tests pass" would be a guess I'm
not willing to hand you as fact.

## 1. The known failing test (`test_database_rate_limit_blocks_after_limit_and_can_reset`)
I traced `enforce_rate_limit`/`reset_rate_limit` in
`backend/app/security/rate_limit.py` line-by-line against the test's call
sequence (create → 2 allowed → 3rd blocked with 429 → reset → allowed again).
The logic is internally consistent and I could not find a defect by static
reading. Rather than make a blind, unverified edit to security-critical
rate-limiting code, I left it untouched.

**Next step (needs your CI, which has the real deps):** run
```
PYTHONPATH=backend pytest -q backend/tests/test_v10_4_security_hardening.py -v
```
and paste me the actual traceback — that will pin the real cause in one pass
instead of guessing.

## 2. CD pipeline — `.github/workflows/cd.yml` (new)
- Triggers only on version tags (`vX.Y.Z`), never on every push to `main` —
  a tag is a deliberate release action, consistent with your existing
  `releases/${BUILD_ID}.env` manifest convention.
- Builds and pushes versioned + `latest` backend/frontend images to GHCR.
- Cuts a GitHub Release with auto-generated notes.
- Deploy-over-SSH job is **off by default** (`vars.RCAA_DEPLOY_ENABLED`) and
  calls your existing `scripts/deploy_production.sh` / `rollback_production.sh`
  rather than reinventing deploy logic — flip the repo variable and add the
  `RCAA_DEPLOY_HOST/USER/SSH_KEY/PATH` secrets when you have a target host.

## 3. Security scanning — `.github/workflows/security.yml` (new)
Runs on push/PR to `main` and weekly on a schedule:
- `pip-audit` against `backend/requirements.txt`
- `npm audit --audit-level=high` against the frontend lockfile
- CodeQL static analysis for Python and JS/TS
- Trivy CRITICAL/HIGH scan of both built images (build-only, not pushed)
- Gitleaks secret scan over full git history

## 4. Dependabot — `.github/dependabot.yml` (updated)
Added Docker-ecosystem tracking for both `backend/Dockerfile` and
`frontend/Dockerfile` (base-image CVEs were previously unmonitored), grouped
minor/patch bumps so they land as one PR instead of a flood, and added
labels for triage.

## What I did not touch
- `ci.yml` — already solid (backend tests, frontend tests/typecheck/lint/build,
  compose config+build). Left as-is until the rate-limit failure is
  root-caused, so I don't compound an unknown issue.
- Application code, migrations, docs — out of scope for "automation."

## Suggested order once you have the real traceback
1. Fix/confirm the rate-limit test → CI goes fully green.
2. Turn on branch protection requiring `ci.yml` + `security.yml` before merge.
3. Set `RCAA_DEPLOY_ENABLED=true` + secrets once you have a deploy target,
   then cut your first tag to exercise `cd.yml` end-to-end.

## 5. Full release pipeline — `.github/workflows/cd.yml` (rewritten)
Now matches: Code → CI Tests → Security Scan → Docker Build → Image Scan →
Staging → Health Check → Production (manual approval) → Monitor/Rollback.

- `ci.yml` and `security.yml` gained `workflow_call:` triggers so the pipeline
  runs the *same* jobs you already have (no duplicated/drifting logic) —
  they still also run standalone on every push/PR as before.
- **Staging is ephemeral**, spun up inside the `staging` job itself via the
  new `docker-compose.staging.yml`, using the exact images that were just
  built and scanned (not a rebuild) — fresh Postgres, fresh secrets
  generated per run, torn down after. It runs `release_health_gate.sh` and
  `smoke_test.sh` against it before anything touches production.
- **Production requires manual approval**: the `production` job uses
  `environment: production`. Add required reviewers to that GitHub
  Environment (Settings → Environments → production) and the job will pause
  and wait for someone to click Approve after staging passes.
- **Monitor/Rollback**: a delayed second health check against the live
  public URL, ~60s after deploy, in case something fails after the
  immediate gate passes. Triggers the same `rollback_production.sh` as an
  immediate deploy failure would.

### Known limitation: frontend image is environment-coupled
`NEXT_PUBLIC_API_URL` is baked into the frontend at build time (a Next.js
constraint), so one frontend image can't correctly serve both a local
staging URL and your real production domain. Set the `RCAA_DOMAIN` repo
variable so the build uses the right one for production; staging then
validates that the image builds, boots, and serves pages, but its API calls
inside the browser won't resolve against the ephemeral stack. The backend
(where all financial-truth logic lives) has no such limitation — it's
fully exercised in staging via direct API calls in `release_health_gate.sh`
and `smoke_test.sh`.

### Required repo configuration for the full pipeline to run
- Variable `RCAA_DEPLOY_ENABLED=true` (gates `production` + `monitor`)
- Variable `RCAA_DOMAIN` (correct frontend build + monitor's health URL)
- Secrets `RCAA_DEPLOY_HOST`, `RCAA_DEPLOY_USER`, `RCAA_DEPLOY_SSH_KEY`, `RCAA_DEPLOY_PATH`
- Required reviewers on the `production` environment
