from .models import RootCauseCategory, RCAConfidence
from .reason_codes import *

RULES = {
    "BANK_SETTLEMENT_MISMATCH": ("BANK_SETTLEMENT_MISMATCH", RootCauseCategory.SETTLEMENT.value, RCAConfidence.HIGH.value,
        "A bank credit was linked to a provider settlement but the credited amount or currency differs from the settlement net amount.",
        "Compare the bank statement, provider settlement, bank charges and any split or adjusted payout records."),
    "BANK_WITHOUT_SETTLEMENT": ("BANK_WITHOUT_SETTLEMENT", RootCauseCategory.PROVIDER.value, RCAConfidence.HIGH.value,
        "A positive bank credit could not be linked to a provider settlement using the configured deterministic matching rules.",
        "Identify the source of the credit and import the corresponding provider settlement or adjustment record."),
    "BANK_AMBIGUOUS_MATCH": ("BANK_AMBIGUOUS_MATCH", RootCauseCategory.MATCHING.value, RCAConfidence.HIGH.value,
        "Multiple bank transactions could represent the same settlement, so no bank credit was selected automatically.",
        "Review the candidate bank transactions and confirm the authoritative payout."),

    "PAYMENT_NOT_SETTLED": (SETTLEMENT_MISSING, RootCauseCategory.SETTLEMENT.value, RCAConfidence.HIGH.value,
        "Payment was captured but no settlement record was found within the configured reconciliation window.",
        "Verify provider settlement status and settlement batch."),
    "DELAYED_SETTLEMENT": (SETTLEMENT_DELAYED, RootCauseCategory.TIMING.value, RCAConfidence.HIGH.value,
        "Payment was captured but settlement was not recorded within the configured settlement timing window.",
        "Verify provider settlement status and settlement batch."),
    "AMOUNT_MISMATCH": (SETTLEMENT_AMOUNT_MISMATCH, RootCauseCategory.SETTLEMENT.value, RCAConfidence.HIGH.value,
        "The recorded settlement amount does not equal the deterministic expected net amount calculated from the payment and supported adjustments.",
        "Compare the provider settlement calculation against the recorded payment, refund, fee and tax components."),
    "STATUS_MISMATCH": (STATUS_INCONSISTENCY, RootCauseCategory.SETTLEMENT.value, RCAConfidence.HIGH.value,
        "The payment and settlement records contain inconsistent financial statuses.",
        "Compare payment and settlement status with the provider records."),
    "DUPLICATE_PAYMENT": (DUPLICATE_PROVIDER_RECORD, RootCauseCategory.DUPLICATION.value, RCAConfidence.HIGH.value,
        "Multiple payment records were identified as the same provider/source record by deterministic duplicate rules.",
        "Review the duplicate provider records and retain the authoritative source record."),
    "DUPLICATE_REFUND": (DUPLICATE_PROVIDER_RECORD, RootCauseCategory.DUPLICATION.value, RCAConfidence.HIGH.value,
        "Multiple refund records were identified as the same provider/source record by deterministic duplicate rules.",
        "Review the duplicate refund records and confirm the authoritative provider record."),
    "DUPLICATE_SETTLEMENT": (DUPLICATE_PROVIDER_RECORD, RootCauseCategory.DUPLICATION.value, RCAConfidence.HIGH.value,
        "Multiple settlement records were identified as the same provider/source record by deterministic duplicate rules.",
        "Review the duplicate settlement records and confirm the authoritative provider record."),
    "AMBIGUOUS_MATCH": (AMBIGUOUS_TRANSACTION_MAPPING, RootCauseCategory.MATCHING.value, RCAConfidence.HIGH.value,
        "Multiple candidate records satisfied the deterministic matching criteria, so no candidate was selected automatically.",
        "Review the candidate settlement records manually."),
    "SETTLEMENT_WITHOUT_PAYMENT": (PROVIDER_REFERENCE_MISMATCH, RootCauseCategory.PROVIDER.value, RCAConfidence.HIGH.value,
        "A settlement record was stored without a corresponding payment record in the normalized financial data.",
        "Verify the provider reference and settlement source data."),
    "REFUND_WITHOUT_PAYMENT": (REFUND_ORPHANED, RootCauseCategory.REFUND.value, RCAConfidence.HIGH.value,
        "A refund record was stored without a corresponding payment record.",
        "Compare the refund reference with provider payment records."),
    "REFUND_NOT_SETTLED": (REFUND_UNSETTLED, RootCauseCategory.REFUND.value, RCAConfidence.MEDIUM.value,
        "A refund exists but the deterministic reconciliation result does not show a settled refund adjustment.",
        "Compare refund status with provider records and settlement data."),
}

def classify(exception_code: str, evidence_complete: bool):
    if not evidence_complete: return INSUFFICIENT_EVIDENCE, RootCauseCategory.UNKNOWN.value, RCAConfidence.UNKNOWN.value, "The available stored evidence is insufficient to determine a supported root cause.", "Collect the missing source records before drawing a root-cause conclusion."
    return RULES.get(exception_code, (UNKNOWN_ROOT_CAUSE, RootCauseCategory.UNKNOWN.value, RCAConfidence.UNKNOWN.value,
        "The deterministic rules do not contain enough evidence to assign a supported root cause.", "Review the stored financial records and reconciliation result."))
