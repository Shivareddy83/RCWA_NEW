# Stage 03 — Multi-source ingestion and deterministic exceptions

## Flow
Source data → validation → normalization → provenance → deterministic reconciliation → exception engine.

## Sources
- `razorpay_api`: provider adapter payloads normalized before persistence.
- `razorpay_webhook`: verified webhook events normalize supported payment/refund/settlement entities.
- `bank_csv`: validated UTF-8 CSV with required `external_id`, `amount`, `currency`, and `event_timestamp`.
- `manual_demo`: normalized JSON imports.

## Idempotency and provenance
Payments, refunds, and settlements retain `source`, `external_id`, `ingestion_batch_id`, `received_at`, and `raw_reference`. Repeated provider/source records are counted as duplicates instead of creating new financial rows. Each import returns received/created/updated/duplicates/rejected statistics.

## Exceptions
The deterministic exception engine maps reconciliation cases to stable codes: `PAYMENT_NOT_SETTLED`, `SETTLEMENT_WITHOUT_PAYMENT`, `REFUND_WITHOUT_PAYMENT`, `REFUND_NOT_SETTLED`, `AMOUNT_MISMATCH`, `STATUS_MISMATCH`, `DUPLICATE_PAYMENT`, `DUPLICATE_REFUND`, `DUPLICATE_SETTLEMENT`, `AMBIGUOUS_MATCH`, `DELAYED_SETTLEMENT`, and `UNKNOWN_REFERENCE`.

Exception fingerprints are deterministic. Repeated reconciliation does not create a second exception for the same unchanged discrepancy. Minimal lifecycle: `OPEN → ACKNOWLEDGED → RESOLVED`. Evidence stores references to actual reconciliation/import records; no invented financial facts are created.

## Safety
CSV validation is transactional and malformed rows report their row number. File size is limited to 5 MB. Financial arithmetic remains Decimal/Numeric. No provider secrets or raw webhook payloads are added to the stored webhook event during Stage 03 processing.
