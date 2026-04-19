from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TranscriptionSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str


class TranscriptionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transcript: str
    language: str | None = None
    inference_seconds: float = Field(ge=0)
    asr_family: str
    asr_provider: str
    model_name: str
    segments: list[TranscriptionSegment] = Field(default_factory=list)


class TranslationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    source_language: str | None = None
    target_language: str = "en"
    inference_seconds: float = Field(ge=0)
    translation_family: str
    translation_provider: str
    model_name: str
