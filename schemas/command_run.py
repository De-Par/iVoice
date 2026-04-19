from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class CommandMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    timestamp: datetime
    duration_seconds: float = Field(ge=0)
    sample_rate: int = Field(ge=1)
    audio_path: str
    source_text: str
    source_modality: str = "audio"
    language: str | None = None
    language_source: str | None = None
    command_en: str
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
    pcs_status: str = "skipped"
    pcs_message: str | None = None
    pcs_family: str | None = None
    pcs_provider: str | None = None
    pcs_model_name: str | None = None
    pcs_inference_seconds: float | None = Field(default=None, ge=0)


class CommandArtifacts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_dir: str
    audio_path: str
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
    ) -> CommandArtifacts:
        resolved_run_dir = Path(run_dir).expanduser().resolve()
        resolved_audio_path = (
            Path(audio_path).expanduser().resolve() if str(audio_path).strip() else Path("")
        )
        return cls(
            run_dir=str(resolved_run_dir),
            audio_path=str(resolved_audio_path) if str(audio_path).strip() else "",
            source_path=str((resolved_run_dir / "source.txt").resolve()),
            command_en_path=str((resolved_run_dir / "command.en.txt").resolve()),
            normalization_spans_path=str((resolved_run_dir / "command.spans.json").resolve()),
            metadata_path=str((resolved_run_dir / "metadata.json").resolve()),
        )


class CommandRun(BaseModel):
    model_config = ConfigDict(extra="ignore")

    artifacts: CommandArtifacts
    metadata: CommandMetadata
