from typing import Any
from pydantic import BaseModel, Field
class ImportEnvelope(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    provider: str | None = Field(default=None, max_length=64)
    records: list[dict[str, Any]] = Field(min_length=1, max_length=10000)
