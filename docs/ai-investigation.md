# Stage 06 — Evidence-Grounded AI Investigation

## Safety boundary

Deterministic reconciliation and deterministic RCA remain the financial source of truth. AI is an investigation assistant only. AI receives a case-scoped structured evidence bundle and deterministic RCA; it has no SQL access, arbitrary tool access, or financial write path.

## Providers

- `AI_PROVIDER=mock` — local, deterministic, no network.
- `AI_PROVIDER=openai_compatible` — optional HTTP provider using `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`, and `AI_TIMEOUT_SECONDS`.

The application starts without an AI key because provider construction occurs only when an investigation is requested.

## Investigation flow

`case -> evidence repository -> evidence bundle -> deterministic RCA -> structured AI context -> provider -> validated result`

External record text is placed in an `UNTRUSTED_EVIDENCE` section and is never treated as instructions. AI output is schema-validated, evidence citations are checked against the current bundle, and prohibited financial actions are rejected.

## Context limits

- question: 2,000 characters
- evidence records: 30
- snapshot: 4,000 characters per item
- total structured context: 30,000 characters

If required evidence cannot fit, the service returns `INSUFFICIENT_CONTEXT` rather than silently dropping evidence.

## API

`POST /api/v1/cases/{id}/ai/investigate`

Request:

```json
{"question":"Why does this settlement mismatch?"}
```

The existing `POST /api/v1/ai/cases/{case_id}/ask` endpoint remains available and now uses the same service while retaining its legacy `answer`, `source`, and `disclaimer` fields.

## Output

The structured result separates facts, deterministic findings, hypotheses, recommended actions, evidence references, uncertainty, provider, model, and prompt version (`rcaa-ai-v1`).

## Audit metadata

`ai_investigation_audits` stores request/evidence fingerprints, prompt version, provider/model, result fingerprint, safe structured result, status, latency, and timestamp. API keys are never stored.
