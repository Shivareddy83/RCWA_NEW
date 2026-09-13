# RCWA 48 — Local Demo Run Guide

This release is the local exploration baseline built from RCAA v0.10.2.
The application name and internal code remain RCAA; the working release folder is named `RCWA_48` as requested.

## Option A — Docker Compose (recommended)

1. Install Docker Desktop.
2. Open a terminal in the project root.
3. Create the local environment file:

```bash
copy .env.example .env
```

On PowerShell, use:

```powershell
Copy-Item .env.example .env
```

4. In `.env`, replace the placeholder `POSTGRES_PASSWORD`, `AUTH_SECRET`, and `AUTH_BOOTSTRAP_TOKEN` values.
5. Keep these local-demo values initially:

```env
APP_ENV=production
AI_PROVIDER=mock
BILLING_PROVIDER=manual
CORS_ORIGINS=http://localhost:3000
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

6. Start everything:

```bash
docker compose up --build
```

7. In a second terminal, seed the representative demo tenant:

```bash
python scripts/seed_demo_data.py
```

If Python is not configured on the host, run the seed command inside the backend container using your Docker setup.

## URLs

- Frontend: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health
- Readiness: http://localhost:8000/ready

## Demo credentials

The seed script creates a demo merchant with these users:

| Role | Email | Password |
|---|---|---|
| ADMIN | admin@demo.local | DemoAdminPass123! |
| OPS | ops@demo.local | DemoOpsPass123! |
| ANALYST | analyst@demo.local | DemoAnalystPass123! |
| VIEWER | viewer@demo.local | DemoViewerPass123! |

These credentials are for local demonstration only. Do not use them in a deployed environment.

## What to explore

1. Login as ADMIN.
2. Open Dashboard.
3. Review Payments, Refunds and Settlements.
4. Open Exceptions.
5. Open an exception and start an investigation.
6. Review evidence and deterministic RCA.
7. Run AI investigation with the default mock provider.
8. Add notes and resolve/reopen a case.
9. Review Audit.
10. Review Jobs and operational state.
11. Open Reports and export exception/case data.
12. Open Notifications.
13. Open Ingestion and inspect the customer data-upload flow.
14. Open Reconciliation and run another reconciliation.
15. Open Billing and inspect the Trial plan.
16. Open Activation / Customer Success views available to the role.
17. Test the public landing/signup/demo flow after logging out.

## Representative financial scenario

The demo seed contains matched and intentionally problematic payment/settlement situations, including settlement mismatches, refunds, delayed settlement, fee/tax differences and ambiguous candidates.

The representative documented scenario is a ₹1,000 payment with ₹25 fee and ₹5 tax, where the expected settlement is ₹970 and the actual settlement is ₹960, creating a deterministic ₹10 discrepancy.

## Razorpay test mode

For local product exploration, keep `BILLING_PROVIDER=manual` unless Razorpay Test Mode credentials and plan IDs have been configured.

When ready for Razorpay Test Mode, configure:

- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `RAZORPAY_WEBHOOK_SECRET`
- `RAZORPAY_PLAN_STARTER`
- `RAZORPAY_PLAN_GROWTH`
- `RAZORPAY_PLAN_BUSINESS`
- `BILLING_PROVIDER=razorpay`

Never commit these values.

## Native frontend development

From `frontend/` after installing dependencies:

```bash
npm install
npm run dev
```

The clean distribution does not include `node_modules`.

## Native backend development

Use PostgreSQL for the normal application run. For lightweight development/testing only, SQLite is supported by the project.

```bash
pip install -r backend/requirements.txt
PYTHONPATH=backend alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend uvicorn app.main:app --app-dir backend --reload
```

## Resetting the Docker demo

To reset all local Docker data and reseed from scratch:

```bash
docker compose down -v
docker compose up --build
```

Then run the seed script again. The `-v` option deletes the local PostgreSQL volume, so use it only when you intentionally want a clean demo.
