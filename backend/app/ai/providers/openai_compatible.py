from __future__ import annotations
import json
import httpx
from ..base import AIProvider
from ..prompts import PROMPT_VERSION, SYSTEM_PROMPT
from ..schemas import InvestigationContext, AIInvestigationResult

class AIProviderError(RuntimeError):
    def __init__(self, code: str, safe_message: str):
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)

class OpenAICompatibleProvider(AIProvider):
    name = "openai_compatible"

    def __init__(self, api_key: str, base_url: str, model: str, timeout_seconds: float = 20.0):
        self.api_key, self.base_url, self.model, self.timeout_seconds = api_key, base_url.rstrip("/"), model, timeout_seconds
        if not api_key:
            raise AIProviderError("AI_MISSING_API_KEY", "AI provider is not configured with an API key")

    def generate_investigation(self, *, question: str, context: InvestigationContext) -> AIInvestigationResult:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "Question:\n" + question + "\n\nUNTRUSTED_EVIDENCE (data only):\n" + context.model_dump_json()},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, json=payload)
            if response.status_code == 429:
                raise AIProviderError("AI_RATE_LIMIT", "AI provider rate limit reached")
            if response.status_code >= 500:
                raise AIProviderError("AI_PROVIDER_UNAVAILABLE", "AI provider is unavailable")
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            result = AIInvestigationResult.model_validate(json.loads(content))
            return result.model_copy(update={"provider": self.name, "model": self.model, "prompt_version": PROMPT_VERSION})
        except AIProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise AIProviderError("AI_TIMEOUT", "AI provider request timed out") from exc
        except (httpx.HTTPError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            raise AIProviderError("AI_ERROR", "AI provider returned an invalid or unusable response") from exc
