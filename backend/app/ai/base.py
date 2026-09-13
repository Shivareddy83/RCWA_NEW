from __future__ import annotations
from abc import ABC, abstractmethod
from .schemas import InvestigationContext, AIInvestigationResult

class AIProvider(ABC):
    name = "unknown"

    @abstractmethod
    def generate_investigation(self, *, question: str, context: InvestigationContext) -> AIInvestigationResult:
        raise NotImplementedError
