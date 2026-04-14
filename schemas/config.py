from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ASRSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    backend: str = "faster_whisper"
    model_name: str = "small"
    model_path: Path | None = None
    device: str = "auto"
    compute_type: str = "int8"
    language: str | None = None
    beam_size: int = Field(default=5, ge=1)
    cpu_threads: int = Field(default=0, ge=0)
    num_workers: int = Field(default=1, ge=1)
    download_root: Path | None = Path("data/models/asr")
    local_files_only: bool = True
    preload_on_startup: bool = False

    @field_validator("language", mode="before")
    @classmethod
    def empty_language_to_none(cls, value: str | None) -> str | None:
        if value in ("", None):
            return None
        return value

    @field_validator("model_path", "download_root", mode="before")
    @classmethod
    def empty_path_to_none(cls, value: str | Path | None) -> Path | None:
        if value in ("", None):
            return None
        return Path(value)


class StorageSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    runs_dir: Path = Path("runs")
    data_dir: Path = Path("data")
    samples_dir: Path = Path("samples")


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    level: str = "INFO"
    rich: bool = True


class APISettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    app_name: str = "smart-voice-kit"
    asr: ASRSettings = ASRSettings()
    storage: StorageSettings = StorageSettings()
    logging: LoggingSettings = LoggingSettings()
    api: APISettings = APISettings()
