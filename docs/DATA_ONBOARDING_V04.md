# RCAA v0.4 — Customer Data Onboarding

## Scope

v0.4 adds the customer-facing path from a raw CSV/XLSX file to validated, imported financial records and a reconciliation trigger. The existing reconciliation engine, financial models, and deterministic matching rules remain unchanged.

## Supported pilot data types

- Payments
- Settlements
- Refunds
- Bank transactions

Orders are not imported as a separate financial table in v0.4 because the existing RCAA domain model does not contain an order ledger. Payment order references remain supported as part of payment data. A separate order ledger can be introduced later without changing this upload contract.

## Customer flow

1. Select data type and provider.
2. Upload CSV or XLSX (maximum 5 MB / 10,000 rows).
3. RCAA parses the file and suggests canonical column mappings.
4. Customer reviews or changes mappings.
5. RCAA validates every row through the existing authoritative normalizer.
6. Customer imports only a validation-passing upload.
7. RCAA records the upload/import in the audit trail.
8. Customer runs the existing deterministic reconciliation endpoint.

## API

- `POST /api/v1/data-onboarding/uploads`
- `GET /api/v1/data-onboarding/uploads`
- `GET /api/v1/data-onboarding/uploads/{upload_id}`
- `POST /api/v1/data-onboarding/uploads/{upload_id}/validate`
- `POST /api/v1/data-onboarding/uploads/{upload_id}/import`
- `POST /api/v1/reconciliation/run`

## Safety boundaries

- Financial persistence is delegated to `app.ingestion`.
- Uploads are tenant-scoped by `merchant_id`.
- Import requires `ADMIN` or `OPS`.
- A validation-failed upload cannot be imported.
- Re-importing an already imported upload is idempotent at the upload workflow level.
- Source financial records retain the existing immutable-record behavior.
- Uploaded staging rows are stored for the pilot workflow; production object storage and retention policies should be added before large-scale public usage.
