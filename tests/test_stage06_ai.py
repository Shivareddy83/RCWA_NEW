from decimal import Decimal
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.main import app, Base, engine
from app.db.session import SessionLocal
from app.models import Case, Payment, Settlement, ReconciliationException, Evidence, RCA, AIInvestigationAudit
from app.ai.schemas import AIInvestigationResult
from app.ai.prompts import SYSTEM_PROMPT, PROMPT_VERSION
from app.ai import service as ai_service
from app.ai.providers.openai_compatible import OpenAICompatibleProvider, AIProviderError

client = TestClient(app)

def reset():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)

def make_case():
    client.post('/api/v1/payments', json={'provider_payment_id':'AI-P1','amount':'1000','currency':'INR','status':'captured'})
    client.post('/api/v1/settlements', json={'provider_settlement_id':'AI-S1','provider_payment_id':'AI-P1','gross_amount':'1000','fee':'25','tax':'5','net_amount':'960','status':'processed','settled_at':'2026-09-02T10:00:00Z'})
    client.post('/api/v1/reconciliation/run')
    exc = client.get('/api/v1/exceptions?exception_code=AMOUNT_MISMATCH').json()['items'][0]
    return client.post('/api/v1/cases', json={'exception_id':exc['id']}).json()

def test_mock_provider_returns_structured_evidence_grounded_result():
    reset(); case=make_case()
    response=client.post(f"/api/v1/cases/{case['id']}/ai/investigate", json={'question':'Why does this settlement mismatch?'})
    assert response.status_code==200
    body=response.json(); ai=body['ai_investigation']
    assert ai['provider']=='mock'
    assert ai['prompt_version']==PROMPT_VERSION
    assert ai['evidence_references']
    assert body['deterministic_rca']['root_cause_code']=='SETTLEMENT_AMOUNT_MISMATCH'
    assert '970.00' in ' '.join(ai['deterministic_findings']) or '970.00' in ' '.join(ai['facts'])

def test_existing_ai_endpoint_is_compatible_and_uses_new_service():
    reset(); case=make_case()
    response=client.post(f"/api/v1/ai/cases/{case['id']}/ask", params={'question':'Why?'})
    assert response.status_code==200
    assert response.json()['ai_investigation']['provider']=='mock'
    assert response.json()['source']=='mock' and response.json()['disclaimer']

def test_context_contains_only_case_evidence_and_deterministic_rca():
    reset(); case=make_case()
    with SessionLocal() as s:
        obj=s.get(Case, case['id']); ctx=ai_service.build_context(s,obj)
    assert ctx.case['id']==case['id']
    assert ctx.deterministic_rca['root_cause_code']=='SETTLEMENT_AMOUNT_MISMATCH'
    assert all('password' not in str(item).lower() for item in ctx.evidence)
    assert len(ctx.evidence) <= ai_service.MAX_EVIDENCE_ITEMS

def test_evidence_context_is_bounded():
    reset(); case=make_case()
    with SessionLocal() as s:
        ev=s.query(Evidence).filter(Evidence.reconciliation_case_id==case['id']).first()
        ev.snapshot_json={'untrusted': 'x' * (ai_service.MAX_SNAPSHOT_CHARS + 1)}; s.commit()
        with pytest.raises(ai_service.AIServiceError, match='snapshot'):
            ai_service.build_context(s,s.get(Case,case['id']))

def test_evidence_ids_are_validated():
    reset(); case=make_case()
    original=ai_service._provider
    class BadProvider:
        name='mock'; model='bad'
        def generate_investigation(self, **kwargs):
            return AIInvestigationResult(summary='x',facts=[],deterministic_findings=[],hypotheses=[],recommended_actions=[],evidence_references=['EV-NOT-IN-CONTEXT'],uncertainty='x',safety_disclaimer='safe',provider='mock',model='bad',prompt_version=PROMPT_VERSION)
    ai_service._provider=lambda: BadProvider()
    try:
        with SessionLocal() as s:
            with pytest.raises(ai_service.AIServiceError, match='evidence'):
                ai_service.investigate(s,s.get(Case,case['id']),'Why?')
    finally: ai_service._provider=original

def test_unsafe_financial_action_in_model_output_is_rejected():
    reset(); case=make_case(); original=ai_service._provider
    class BadProvider:
        name='mock'; model='bad'
        def generate_investigation(self, **kwargs):
            return AIInvestigationResult(summary='x',facts=[],deterministic_findings=[],hypotheses=[],recommended_actions=['Issue refund automatically'],evidence_references=[],uncertainty='x',safety_disclaimer='safe',provider='mock',model='bad',prompt_version=PROMPT_VERSION)
    ai_service._provider=lambda: BadProvider()
    try:
        with SessionLocal() as s:
            with pytest.raises(ai_service.AIServiceError, match='prohibited'):
                ai_service.investigate(s,s.get(Case,case['id']),'Why?')
    finally: ai_service._provider=original

def test_prompt_injection_rules_treat_financial_content_as_untrusted_data():
    assert 'UNTRUSTED_EVIDENCE' in SYSTEM_PROMPT
    assert 'never as instructions' in SYSTEM_PROMPT
    assert 'Do not invent' in SYSTEM_PROMPT

def test_ai_call_does_not_change_financial_records_or_deterministic_rca():
    reset(); case=make_case()
    before=client.get('/api/v1/payments').json()['items'][0], client.get('/api/v1/settlements').json()['items'][0]
    rca_before=client.get(f"/api/v1/cases/{case['id']}/rca").json()
    response=client.post(f"/api/v1/cases/{case['id']}/ai/investigate", json={'question':'Why does this mismatch?'})
    assert response.status_code==200
    after=client.get('/api/v1/payments').json()['items'][0], client.get('/api/v1/settlements').json()['items'][0]
    rca_after=client.get(f"/api/v1/cases/{case['id']}/rca").json()
    assert before==after
    assert rca_before['root_cause_code']==rca_after['root_cause_code']=='SETTLEMENT_AMOUNT_MISMATCH'
    assert rca_before['evidence_ids']==rca_after['evidence_ids']

def test_repeated_identical_request_reuses_deterministic_result():
    reset(); case=make_case()
    one=client.post(f"/api/v1/cases/{case['id']}/ai/investigate", json={'question':'Why does this mismatch?'}).json()
    two=client.post(f"/api/v1/cases/{case['id']}/ai/investigate", json={'question':'Why does this mismatch?'}).json()
    assert one['ai_investigation']==two['ai_investigation']
    with SessionLocal() as s:
        assert s.query(AIInvestigationAudit).filter(AIInvestigationAudit.case_id==case['id']).count()==1

def test_different_questions_do_not_share_cache():
    reset(); case=make_case()
    one=client.post(f"/api/v1/cases/{case['id']}/ai/investigate", json={'question':'Why does this mismatch?'}).json()
    two=client.post(f"/api/v1/cases/{case['id']}/ai/investigate", json={'question':'What should I investigate next?'}).json()
    assert one['request_fingerprint'] != two['request_fingerprint']
    with SessionLocal() as s:
        assert s.query(AIInvestigationAudit).filter(AIInvestigationAudit.case_id==case['id']).count()==2

def test_missing_ai_key_is_controlled_when_real_provider_selected(monkeypatch):
    reset(); case=make_case()
    monkeypatch.setattr(ai_service, 'settings', SimpleNamespace(ai_provider='openai_compatible', ai_api_key='', ai_base_url='https://example.invalid/v1', ai_model='model', ai_timeout_seconds=1))
    response=client.post(f"/api/v1/cases/{case['id']}/ai/investigate", json={'question':'Why?'})
    assert response.status_code==503
    assert 'API key' in response.json()['detail']

def test_openai_provider_timeout_is_safe(monkeypatch):
    class TimeoutClient:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,*args,**kwargs):
            import httpx
            raise httpx.TimeoutException('secret internal detail')
    monkeypatch.setattr('httpx.Client', lambda *args, **kwargs: TimeoutClient())
    provider=OpenAICompatibleProvider('key','https://example.invalid/v1','model',1)
    with pytest.raises(AIProviderError) as exc:
        provider.generate_investigation(question='Why?', context=SimpleNamespace(model_dump_json=lambda: '{}'))
    assert exc.value.code=='AI_TIMEOUT'
    assert 'secret internal' not in exc.value.safe_message

def test_malformed_provider_response_is_safe():
    class BadResponse:
        status_code=200
        def raise_for_status(self): pass
        def json(self): return {'choices':[{'message':{'content':'not-json'}}]}
    class Client:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,*args,**kwargs): return BadResponse()
    import httpx
    original=httpx.Client
    httpx.Client= lambda *args, **kwargs: Client()
    try:
        provider=OpenAICompatibleProvider('key','https://example.invalid/v1','model',1)
        with pytest.raises(AIProviderError) as exc:
            provider.generate_investigation(question='Why?', context=SimpleNamespace(model_dump_json=lambda: '{}'))
        assert exc.value.code=='AI_ERROR'
    finally: httpx.Client=original

def test_ai_failure_does_not_create_or_modify_financial_records():
    reset(); case=make_case(); before=client.get('/api/v1/payments').json()['items'][0]
    original=ai_service._provider
    class FailProvider:
        name='mock'; model='fail'
        def generate_investigation(self, **kwargs): raise ai_service.AIServiceError('AI_ERROR','AI unavailable')
    ai_service._provider=lambda: FailProvider()
    try:
        with SessionLocal() as s:
            with pytest.raises(ai_service.AIServiceError): ai_service.investigate(s,s.get(Case,case['id']),'Why?')
    finally: ai_service._provider=original
    after=client.get('/api/v1/payments').json()['items'][0]
    assert before==after


def test_openai_provider_5xx_is_safe(monkeypatch):
    class Response:
        status_code=503
        def raise_for_status(self): pass
    class Client:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,*args,**kwargs): return Response()
    monkeypatch.setattr('httpx.Client', lambda *args, **kwargs: Client())
    provider=OpenAICompatibleProvider('key','https://example.invalid/v1','model',1)
    with pytest.raises(AIProviderError) as exc:
        provider.generate_investigation(question='Why?', context=SimpleNamespace(model_dump_json=lambda: '{}'))
    assert exc.value.code=='AI_PROVIDER_UNAVAILABLE'

def test_ai_output_cannot_resolve_case():
    reset(); case=make_case(); original=ai_service._provider
    class BadProvider:
        name='mock'; model='bad'
        def generate_investigation(self, **kwargs):
            return AIInvestigationResult(summary='x',facts=[],deterministic_findings=[],hypotheses=[],recommended_actions=['Resolve case now'],evidence_references=[],uncertainty='x',safety_disclaimer='safe',provider='mock',model='bad',prompt_version=PROMPT_VERSION)
    ai_service._provider=lambda: BadProvider()
    try:
        with SessionLocal() as s:
            with pytest.raises(ai_service.AIServiceError, match='prohibited'):
                ai_service.investigate(s,s.get(Case,case['id']),'Why?')
    finally: ai_service._provider=original
