from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    timestamp: datetime
    duration_seconds: float = Field(ge=0)
    sample_rate: int = Field(ge=1)
    audio_path: str
    source_text: str | None = None
    source_modality: str = "audio"
    language: str | None = None
    language_source: str | None = None
    transcript: str
    transcript_en: str
    command_en: str | None = None
    normalization_spans_path: str | None = None
    normalization_span_count: int = 0
    target_language: str = "en"
    normalization_status: str = "disabled"
    normalization_message: str | None = None
    translation_status: str = "disabled"
    translation_message: str | None = None
    inference_seconds: float = Field(ge=0)
    asr_family: str
    asr_provider: str
    asr_model_name: str
    translation_family: str | None = None
    translation_provider: str | None = None
    translation_model_name: str | None = None
    translation_inference_seconds: float | None = Field(default=None, ge=0)


class RunArtifacts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_dir: str
    audio_path: str
    transcript_path: str
    transcript_en_path: str
    source_path: str
    command_en_path: str
    normalization_spans_path: str
    metadata_path: str

    @classmethod
    def from_run_dir(
        cls,
        run_dir: str | Path,
        *,
        audio_path: str | Path = "",
    ) -> RunArtifacts:
        resolved_run_dir = Path(run_dir).expanduser().resolve()
        resolved_audio_path = (
            Path(audio_path).expanduser().resolve() if str(audio_path).strip() else Path("")
        )
        return cls(
            run_dir=str(resolved_run_dir),
            audio_path=str(resolved_audio_path) if str(audio_path).strip() else "",
            transcript_path=str((resolved_run_dir / "transcript.txt").resolve()),
            transcript_en_path=str((resolved_run_dir / "transcript.en.txt").resolve()),
            source_path=str((resolved_run_dir / "source.txt").resolve()),
            command_en_path=str((resolved_run_dir / "command.en.txt").resolve()),
            normalization_spans_path=str((resolved_run_dir / "command.spans.json").resolve()),
            metadata_path=str((resolved_run_dir / "metadata.json").resolve()),
        )


class TranscriptionRun(BaseModel):
    model_config = ConfigDict(extra="ignore")

    artifacts: RunArtifacts
    metadata: RunMetadata

    @model_validator(mode="before")
    @classmethod
    def migrate_flat_paths(cls, value: object) -> object:
        if not isinstance(value, dict) or "artifacts" in value:
            return value

        run_dir = value.get("run_dir")
        if run_dir is None:
            return value

        artifacts = RunArtifacts.from_run_dir(
            run_dir,
            audio_path=value.get("audio_path", ""),
        ).model_dump(mode="json")
        return {
            **value,
            "artifacts": artifacts,
        }
