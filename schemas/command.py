from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LanguageResolution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    language: str | None = None
    source: str = "unknown"


class CommandSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    modality: str = "text"
    language: str | None = None
    language_source: str = "unknown"


class CommandSpan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    kind: str = "text"
    language: str | None = None
    language_source: str = "unknown"
    status: str = "literal"
    normalized_text: str | None = None
    translation_family: str | None = None
    translation_provider: str | None = None
    translation_model_name: str | None = None


class NormalizedCommand(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    target_language: str = "en"
    status: str = "disabled"
    message: str | None = None
    translated_span_count: int = 0
    preserved_span_count: int = 0
    translation_family: str | None = None
    translation_provider: str | None = None
    translation_model_name: str | None = None
    translation_inference_seconds: float | None = Field(default=None, ge=0)


class CommandNormalizationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: CommandSource
    normalized: NormalizedCommand
    spans: list[CommandSpan] = Field(default_factory=list)
