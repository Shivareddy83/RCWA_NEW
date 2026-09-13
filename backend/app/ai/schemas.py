from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field, field_validator

class InvestigationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case: dict
    exceptions: list[dict]
    evidence: list[dict]
    deterministic_rca: dict | None
    relevant_financial_values: dict
    provenance: list[dict]
    allowed_actions: list[str]
    evidence_fingerprint: str
    context_fingerprint: str

class AIInvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=4000)
    facts: list[str] = Field(default_factory=list, max_length=20)
    deterministic_findings: list[str] = Field(default_factory=list, max_length=20)
    hypotheses: list[str] = Field(default_factory=list, max_length=20)
    recommended_actions: list[str] = Field(default_factory=list, max_length=20)
    evidence_references: list[str] = Field(default_factory=list, max_length=50)
    uncertainty: str = Field(default="", max_length=2000)
    safety_disclaimer: str = Field(min_length=1, max_length=1000)
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(default="", max_length=200)
    prompt_version: str = Field(min_length=1, max_length=100)

    @field_validator("facts", "deterministic_findings", "hypotheses", "recommended_actions", "evidence_references")
    @classmethod
    def no_blank_items(cls, value):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
