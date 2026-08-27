from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NewsEventType(StrEnum):
    ADOPTION = "adoption"
    LISTING = "listing"
    MACRO = "macro"
    MARKET = "market"
    PROTOCOL = "protocol"
    REGULATION = "regulation"
    SECURITY = "security"
    OTHER = "other"


class NewsEventExtraction(BaseModel):
    """Strict, versioned boundary between an LLM response and the domain model."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    assets: list[str] = Field(default_factory=list, max_length=20)
    event_type: NewsEventType
    direction: float = Field(ge=-1.0, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    horizon_seconds: int = Field(gt=0, le=30 * 24 * 60 * 60)
    summary: str = Field(min_length=1, max_length=1000)

    @field_validator("assets")
    @classmethod
    def normalize_assets(cls, assets: list[str]) -> list[str]:
        normalized: list[str] = []
        for asset in assets:
            ticker = asset.strip().upper()
            if not ticker or len(ticker) > 15 or not ticker.replace("-", "").isalnum():
                raise ValueError(f"invalid asset ticker: {asset!r}")
            if ticker not in normalized:
                normalized.append(ticker)
        return normalized
