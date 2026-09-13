# RCAA Frontend

Stage 12 adds a production-oriented Next.js operations console over the existing FastAPI contracts. The backend remains authoritative for authentication, RBAC, tenant isolation, reconciliation, RCA, AI safety, financial values and job state.

## Architecture
- `frontend/app`: App Router pages
- `frontend/components`: shell, tables, states and shared controls
- `frontend/lib/api.ts`: centralized authenticated API client and normalized errors
- `frontend/lib/auth.tsx`: in-memory authentication state
- `frontend/lib/format.ts`: display-only money/date formatting
- `frontend/lib/permissions.ts`: role-based UX capability checks
- `frontend/lib/pagination.ts`: bounded backend pagination query construction
- `frontend/types`: backend-facing TypeScript types

## Routes
Dashboard, payments, refunds, settlements, exceptions, cases, case investigation, jobs, audit, ingestion, reconciliation, login and admin users.

## Authentication
Login calls `POST /api/v1/auth/login`, then `GET /api/v1/auth/me`. The access token is held in frontend memory and is not written to localStorage, source code, logs or UI. Logout clears the token and redirects to login.

## API integration
All browser data requests use the centralized API client. It sends the bearer token and a request ID, and maps 401/403/404/422/429/5xx responses into safe UI errors. The browser never calls an AI or payment provider directly.

## Role-aware UI
The UI hides operational mutations from VIEWER/ANALYST where backend permissions do not allow them. ADMIN user management uses the existing POST/PATCH user APIs. These controls are UX only; backend authorization remains the security boundary.

## Financial formatting
Amounts are treated as backend-provided decimal-like values and formatted with string-based grouping/precision. The frontend never recomputes settlement, reconciliation, fee, tax, refund or RCA values.

## AI safety UX
The case workspace labels AI as assistive and separates summary, deterministic findings, hypotheses, recommendations, evidence references and uncertainty. Investigation requests go through the existing backend endpoint.

## Environment
Set `NEXT_PUBLIC_API_URL` to the FastAPI API base, for example `http://127.0.0.1:8000/api/v1` for local development. Do not place secrets in `NEXT_PUBLIC_*` variables.

## Build
`npm run build` produces the production Next.js build. The frontend test suite uses Node's built-in test runner and exercises authentication state, role visibility, financial formatting, pagination, API error mapping, and source-level investigation/error-state contracts. `npm run lint` is a lightweight source-hygiene check rather than ESLint. A real TypeScript/Next production build requires the declared npm dependencies to be installed.

## Verification status
- Backend regression: 173 passed / 0 failed.
- Frontend tests: 19 passed / 0 failed.
- Frontend lint: PASS (source-hygiene check).
- Backend runtime was exercised against a clean migrated SQLite database, including health/ready, login, dashboard/resources, reconciliation, RCA, AI investigation and case action/audit flow.
- Frontend typecheck, production build and browser E2E could not be completed in the execution environment because outbound npm registry access fails with DNS/network `EAI_AGAIN`; no partial dependency tree was treated as a successful install.
