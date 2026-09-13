# Fintech Operations Runbook

The first rule for every incident is: **do not bypass financial controls or mutate financial records to make an incident appear resolved.**

| Incident | Detection | Immediate action | Safety / recovery | Verification |
|---|---|---|---|---|
| API unavailable | health check or client failures | inspect backend logs and container state | restart only after identifying the cause; PostgreSQL remains the source of truth | `/health`, `/ready`, authenticated smoke test |
| PostgreSQL unavailable | `/ready` fails, DB errors | inspect PostgreSQL health/logs | restore connectivity; do not retry financial writes blindly | `/ready`, transaction read check |
| Worker unavailable | queued jobs stop progressing | inspect worker logs/state | restart worker; expired leases are recoverable | queue → claim → execute → terminal state |
| Jobs stuck | RUNNING lease expires | inspect job attempt/lease fields | allow stale-lease recovery; do not manually mark successful | job state and audit event |
| Retry storm | retry/dead-letter metrics rise | stop repeated external triggering and inspect root cause | preserve bounded retry settings | retry count, final state, no duplicate financial record |
| Failed migration | backend fails before ready | stop application rollout | inspect Alembic error; restore or repair safely; never delete financial data | `alembic current`, readiness, regression tests |
| Frontend unavailable | frontend health check fails | inspect frontend container/logs | restart/redeploy image | frontend health and API smoke test |
| AI provider unavailable | AI request returns safe provider error | use deterministic RCA/evidence already persisted | do not invent a conclusion or financial action | case RCA/evidence remains intact |
| Audit verification failure | hash-chain verification fails | treat as integrity incident | preserve affected data/logs and investigate; do not rewrite the chain | independent hash verification |
| Reconciliation failure | reconciliation run fails | inspect job/API error and persisted state | retry only through supported idempotent path | results, exceptions, RCA, audit |

## Graceful deployment

For a worker deployment, stop accepting new work through the process supervisor, allow the current synchronous operation to finish where possible, then stop the worker. If the process is terminated abruptly, the lease mechanism allows recovery after expiry.

## Security incidents

For missing/invalid JWT, cross-tenant access, unauthorized mutation, unsafe AI output, or job ownership violations, preserve the denied outcome and audit evidence. Never weaken authorization to restore service.
