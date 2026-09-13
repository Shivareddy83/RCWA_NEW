from dataclasses import dataclass
from enum import Enum

class RootCauseCategory(str, Enum):
    PROVIDER="PROVIDER"; SETTLEMENT="SETTLEMENT"; REFUND="REFUND"; BANK="BANK"; DATA_QUALITY="DATA_QUALITY"; DUPLICATION="DUPLICATION"; MATCHING="MATCHING"; TIMING="TIMING"; UNKNOWN="UNKNOWN"
class RCAConfidence(str, Enum):
    HIGH="HIGH"; MEDIUM="MEDIUM"; LOW="LOW"; UNKNOWN="UNKNOWN"

@dataclass(frozen=True)
class RCAResult:
    case_id: str
    exception_id: str | None
    root_cause_code: str
    root_cause_category: str
    confidence: str
    explanation: str
    recommended_action: str
    evidence_ids: list[str]
    generated_at: str
    engine_version: str
