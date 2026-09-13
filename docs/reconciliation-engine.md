# Reconciliation engine

The reconciliation engine is deterministic: identical financial records and configuration produce the same result. Matching proceeds from provider payment ID, to normalized order/provider references, to UTR/bank/settlement references, and finally to amount + currency + configured time tolerance. Ambiguous candidates are never auto-selected.

Every reconciliation exception carries a machine-readable reason code, match method/confidence, expected and actual amounts, difference, and supporting metadata. Money calculations use `Decimal`/database `Numeric` semantics.

Expected settlement is calculated as gross payment amount minus processed/created refunds, fees, and tax, plus explicitly supplied settlement adjustments. The actual amount is the sum of matched settlement net amounts.

The engine also classifies missing payments/settlements/refunds, currency mismatches, delayed settlements, duplicate source rows, status mismatches, and amount mismatches. Re-running reconciliation uses deterministic case fingerprints and does not create duplicate cases.
