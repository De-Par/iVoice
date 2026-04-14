from __future__ import annotations

from datetime import datetime

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
    asr_backend: str
    model_name: str
    segments: list[TranscriptionSegment] = Field(default_factory=list)

    # TODO(next): extend with style control hints and speaker metadata.


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    timestamp: datetime
    duration_seconds: float = Field(ge=0)
    sample_rate: int = Field(ge=1)
    audio_path: str
    language: str | None = None
    transcript: str
    inference_seconds: float = Field(ge=0)
    asr_backend: str
    model_name: str


class TranscriptionRun(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_dir: str
    audio_path: str
    transcript_path: str
    metadata_path: str
    metadata: RunMetadata
