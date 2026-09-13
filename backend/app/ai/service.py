from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import AIInvestigationAudit, Case, CaseExceptionLink, Evidence, ReconciliationException
from app.evidence.repository import list_case_evidence
from app.services.serialization import dump
from .prompts import PROMPT_VERSION
from .providers import MockAIProvider, OpenAICompatibleProvider
from .providers.openai_compatible import AIProviderError
from .schemas import InvestigationContext, AIInvestigationResult
from app.observability.metrics import inc, observe

MAX_QUESTION_CHARS = 2000
MAX_EVIDENCE_ITEMS = 30
MAX_SNAPSHOT_CHARS = 4000
MAX_CONTEXT_CHARS = 30000

class AIServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)

def _fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

def _provider():
    name = (settings.ai_provider or "mock").strip().lower()
    if name in {"mock", "deterministic"}:
        return MockAIProvider()
    if name in {"openai", "openai_compatible"}:
        return OpenAICompatibleProvider(settings.ai_api_key, settings.ai_base_url, settings.ai_model, settings.ai_timeout_seconds)
    raise AIServiceError("AI_PROVIDER_CONFIG", "Unsupported AI provider configuration")

def build_context(session: Session, case: Case) -> InvestigationContext:
    exceptions = session.scalars(select(ReconciliationException).join(CaseExceptionLink, CaseExceptionLink.exception_id == ReconciliationException.id).where(CaseExceptionLink.case_id == case.id).order_by(ReconciliationException.created_at, ReconciliationException.id)).all()
    evidence = list_case_evidence(session, case.id)
    if len(evidence) > MAX_EVIDENCE_ITEMS:
        raise AIServiceError("INSUFFICIENT_CONTEXT", "Investigation evidence exceeds the configured context record limit")
    evidence_dicts = []
    for item in evidence:
        snapshot = item.snapshot_json or {}
        encoded = json.dumps(snapshot, sort_keys=True, default=str)
        if len(encoded) > MAX_SNAPSHOT_CHARS:
            raise AIServiceError("INSUFFICIENT_CONTEXT", "A required evidence snapshot exceeds the configured context size")
        evidence_dicts.append({"id": item.id, "evidence_type": item.evidence_type, "source_entity_type": item.source_entity_type, "source_record_id": item.source_record_id, "captured_at": item.captured_at.isoformat() if item.captured_at else None, "relevance": item.relevance, "snapshot": snapshot})
    rca = case.rca
    rca_dict = None
    if rca:
        rca_dict = {"root_cause_code": rca.root_cause, "category": rca.root_cause_category, "confidence": rca.confidence_label, "explanation": rca.explanation, "recommended_action": rca.recommended_action, "evidence_ids": rca.evidence_ids_json or [], "engine_version": rca.engine_version}
    financial = {"expected_amount": str(case.expected_amount), "actual_amount": str(case.actual_amount), "difference": str(case.difference)}
    for ev in evidence_dicts:
        snap = ev["snapshot"]
        if ev["evidence_type"] == "PAYMENT_RECORD": financial.setdefault("payment_amount", snap.get("amount"))
        if ev["evidence_type"] == "SETTLEMENT_RECORD": financial.setdefault("settlement_amount", snap.get("net_amount"))
        if ev["evidence_type"] == "REFUND_RECORD": financial.setdefault("refund_amount", snap.get("amount"))
    case_data = {"id": case.id, "case_number": case.case_number, "merchant_id": case.merchant_id, "title": case.title, "status": case.status, "priority": case.priority, "severity": case.severity, "record_id": case.record_id, "record_type": case.record_type}
    exc_data = [{"id": e.id, "exception_code": e.exception_code, "severity": e.severity, "status": e.status, "primary_record_id": e.primary_record_id, "related_record_id": e.related_record_id, "expected_amount": str(e.expected_amount), "actual_amount": str(e.actual_amount), "difference": str(e.difference)} for e in exceptions]
    provenance = [{"evidence_id": e["id"], "source_entity_type": e["source_entity_type"], "source_record_id": e["source_record_id"], "captured_at": e["captured_at"]} for e in evidence_dicts]
    base = {"case": case_data, "exceptions": exc_data, "evidence": evidence_dicts, "deterministic_rca": rca_dict, "relevant_financial_values": financial, "provenance": provenance, "allowed_actions": ["summarize evidence", "explain deterministic findings", "suggest investigation questions", "recommend operational next steps"], "evidence_fingerprint": _fingerprint(evidence_dicts)}
    context_json = json.dumps(base, sort_keys=True, separators=(",", ":"), default=str)
    if len(context_json) > MAX_CONTEXT_CHARS:
        raise AIServiceError("INSUFFICIENT_CONTEXT", "Required investigation evidence exceeds the configured context size")
    base["context_fingerprint"] = _fingerprint(base)
    return InvestigationContext.model_validate(base)

def _validate_citations(result: AIInvestigationResult, context: InvestigationContext) -> AIInvestigationResult:
    valid = {e["id"] for e in context.evidence}
    invalid = [x for x in result.evidence_references if x not in valid]
    if invalid:
        raise AIServiceError("INVALID_EVIDENCE_CITATION", "AI response referenced evidence outside the investigation context")
    forbidden = ("issue refund", "mark settled", "settle transaction", "change payment amount", "update payment", "update settlement", "modify refund", "resolve case", "execute sql", "reveal api key")
    text = " ".join(result.facts + result.deterministic_findings + result.hypotheses + result.recommended_actions + [result.summary, result.uncertainty]).lower()
    if any(term in text for term in forbidden):
        raise AIServiceError("UNSAFE_AI_OUTPUT", "AI response contained a prohibited financial or privileged action")
    return result

def investigate(session: Session, case: Case, question: str) -> tuple[AIInvestigationResult, str]:
    question = (question or "").strip()
    if not question: raise AIServiceError("INVALID_QUESTION", "question must not be empty")
    if len(question) > MAX_QUESTION_CHARS: raise AIServiceError("QUESTION_TOO_LONG", "question exceeds the configured length limit")
    context = build_context(session, case)
    try:
        provider = _provider()
    except AIProviderError as exc:
        raise AIServiceError(exc.code, exc.safe_message) from exc
    request_key = _fingerprint({"case_id": case.id, "evidence_fingerprint": context.evidence_fingerprint, "question": question, "prompt_version": PROMPT_VERSION, "provider": provider.name, "model": getattr(provider, "model", "")})
    cached = session.scalar(select(AIInvestigationAudit).where(AIInvestigationAudit.request_fingerprint == request_key, AIInvestigationAudit.status == "SUCCEEDED"))
    if cached and cached.result_json:
        inc("ai_investigations_reused_total")
        inc("ai_investigations_total", labels={"failure_category": "none", "provider": getattr(provider, "name", "unknown")})
        return AIInvestigationResult.model_validate(cached.result_json), request_key
    started = datetime.now(timezone.utc)
    inc("ai_investigations_total", labels={"failure_category": "none", "provider": getattr(provider, "name", "unknown")})
    try:
        result = _validate_citations(provider.generate_investigation(question=question, context=context), context)
    except AIProviderError as exc:
        audit = AIInvestigationAudit(case_id=case.id, request_fingerprint=request_key, evidence_fingerprint=context.evidence_fingerprint, prompt_version=PROMPT_VERSION, provider=getattr(provider, "name", "unknown"), model=getattr(provider, "model", ""), status=exc.code, latency_ms=int((datetime.now(timezone.utc)-started).total_seconds()*1000))
        session.add(audit); session.commit()
        category = {"AI_TIMEOUT":"timeout", "AI_PROVIDER_5XX":"provider_unavailable", "AI_RATE_LIMIT":"rate_limit", "AI_PROVIDER_UNAVAILABLE":"provider_unavailable"}.get(exc.code, "configuration_error" if "CONFIG" in exc.code else "provider_unavailable")
        inc("ai_investigations_failed_total", labels={"failure_category": category, "provider": getattr(provider, "name", "unknown")})
        observe("ai_investigation_duration_seconds", (datetime.now(timezone.utc)-started).total_seconds())
        raise AIServiceError(exc.code, exc.safe_message) from exc
    except AIServiceError as exc:
        category = {"INVALID_EVIDENCE_CITATION":"invalid_citation", "UNSAFE_AI_OUTPUT":"unsafe_output", "INSUFFICIENT_CONTEXT":"insufficient_context"}.get(exc.code, "invalid_response")
        inc("ai_investigations_failed_total", labels={"failure_category": category, "provider": getattr(provider, "name", "unknown")})
        observe("ai_investigation_duration_seconds", (datetime.now(timezone.utc)-started).total_seconds())
        raise
    except Exception as exc:
        audit = AIInvestigationAudit(case_id=case.id, request_fingerprint=request_key, evidence_fingerprint=context.evidence_fingerprint, prompt_version=PROMPT_VERSION, provider=getattr(provider, "name", "unknown"), model=getattr(provider, "model", ""), status="AI_ERROR", latency_ms=int((datetime.now(timezone.utc)-started).total_seconds()*1000))
        session.add(audit); session.commit()
        inc("ai_investigations_failed_total", labels={"failure_category": "invalid_response", "provider": getattr(provider, "name", "unknown")})
        observe("ai_investigation_duration_seconds", (datetime.now(timezone.utc)-started).total_seconds())
        raise AIServiceError("AI_ERROR", "AI investigation could not be completed safely") from exc
    result_fp = _fingerprint(result.model_dump())
    audit = AIInvestigationAudit(case_id=case.id, request_fingerprint=request_key, evidence_fingerprint=context.evidence_fingerprint, prompt_version=PROMPT_VERSION, provider=result.provider, model=result.model, result_fingerprint=result_fp, result_json=result.model_dump(), status="SUCCEEDED", latency_ms=int((datetime.now(timezone.utc)-started).total_seconds()*1000))
    session.add(audit); session.commit()
    inc("ai_investigations_success_total", labels={"provider": result.provider})
    observe("ai_investigation_duration_seconds", (datetime.now(timezone.utc)-started).total_seconds())
    return result, request_key
