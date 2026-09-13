from __future__ import annotations
from ..base import AIProvider
from ..prompts import PROMPT_VERSION
from ..schemas import InvestigationContext, AIInvestigationResult

class MockAIProvider(AIProvider):
    name = "mock"
    model = "mock-v1"

    def generate_investigation(self, *, question: str, context: InvestigationContext) -> AIInvestigationResult:
        rca = context.deterministic_rca or {}
        evidence_ids = [item.get("id") for item in context.evidence if item.get("id")]
        facts = []
        financial = context.relevant_financial_values
        for label in ("payment_amount", "settlement_amount", "refund_amount", "expected_amount", "actual_amount", "difference"):
            if label in financial and financial[label] is not None:
                facts.append(f"{label.replace('_', ' ').capitalize()} = {financial[label]}")
        deterministic = []
        if rca.get("root_cause_code"):
            deterministic.append(f"Deterministic RCA: {rca['root_cause_code']}")
        if rca.get("explanation"):
            deterministic.append(rca["explanation"])
        hypotheses = []
        if rca.get("root_cause_code") == "SETTLEMENT_AMOUNT_MISMATCH":
            hypotheses.append("A provider settlement component may differ from the stored calculation; this is a hypothesis, not a proven provider-side cause.")
        elif rca.get("root_cause_code") == "AMBIGUOUS_TRANSACTION_MAPPING":
            hypotheses.append("The available records do not uniquely identify the correct settlement candidate.")
        elif not rca.get("root_cause_code") or rca.get("root_cause_code") in {"UNKNOWN_ROOT_CAUSE", "INSUFFICIENT_EVIDENCE"}:
            hypotheses.append("The supplied evidence does not establish a more specific root cause.")
        actions = [rca.get("recommended_action")] if rca.get("recommended_action") else ["Review the supplied evidence and deterministic findings before taking an operational action."]
        uncertainty = "The mock provider does not add external facts; provider-side causes are not established unless present in supplied evidence."
        if rca.get("confidence") == "UNKNOWN":
            uncertainty = "The deterministic RCA reports insufficient evidence; no stronger conclusion is supported."
        return AIInvestigationResult(
            summary=f"Investigation of case {context.case.get('case_number', context.case.get('id', 'unknown'))} for: {question.strip()}",
            facts=facts,
            deterministic_findings=deterministic,
            hypotheses=hypotheses,
            recommended_actions=actions,
            evidence_references=evidence_ids,
            uncertainty=uncertainty,
            safety_disclaimer="AI output is investigative assistance and not financial truth.",
            provider=self.name, model=self.model, prompt_version=PROMPT_VERSION,
        )
