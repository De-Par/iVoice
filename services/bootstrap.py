from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from core.asr import build_asr_engine
from core.logging import configure_logging
from core.settings import load_settings
from schemas.config import AppSettings
from services.transcription import TranscriptionService


@dataclass(frozen=True)
class AppContext:
    settings: AppSettings
    service: TranscriptionService


@lru_cache(maxsize=4)
def build_app_context(
    config_path: str | Path | None = None,
    asr_local_files_only_override: bool | None = None,
) -> AppContext:
    settings = load_settings(config_path)
    if asr_local_files_only_override is not None:
        updated_asr = settings.asr.model_copy(
            update={"local_files_only": asr_local_files_only_override}
        )
        settings = settings.model_copy(update={"asr": updated_asr})
    configure_logging(settings.logging)
    asr_engine = build_asr_engine(settings)
    service = TranscriptionService(settings=settings, asr_engine=asr_engine)
    if settings.asr.preload_on_startup:
        service.warm_up_asr()
    return AppContext(settings=settings, service=service)
