from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from core.asr import build_asr_engine
from core.logging import configure_logging
from core.settings import load_settings
from core.translation import build_translation_engine
from schemas.config import AppSettings
from services.prepare_model import (
    build_asr_model_descriptor,
    build_asr_model_request,
    build_translation_model_descriptor,
    build_translation_model_request,
)
from services.transcription import TranscriptionService


@dataclass(frozen=True)
class AppContext:
    settings: AppSettings
    service: TranscriptionService


@lru_cache(maxsize=4)
def build_app_context(
    config_path: str | Path | None = None,
    asr_local_files_only_override: bool | None = None,
    warm_up_on_startup: bool | None = None,
) -> AppContext:
    settings = load_settings(config_path)
    if asr_local_files_only_override is not None:
        updated_asr = settings.asr.model_copy(
            update={"local_files_only": asr_local_files_only_override}
        )
        settings = settings.model_copy(update={"asr": updated_asr})
    configure_logging(settings.logging)
    asr_descriptor = build_asr_model_descriptor(settings)
    translation_descriptor = build_translation_model_descriptor(settings)
    asr_engine = build_asr_engine(asr_descriptor)
    translation_engine = build_translation_engine(translation_descriptor)
    service = TranscriptionService(
        settings=settings,
        asr_engine=asr_engine,
        translation_engine=translation_engine,
        asr_request=build_asr_model_request(settings),
        translation_request=build_translation_model_request(settings),
    )
    should_warm_up = warm_up_on_startup
    if should_warm_up is None:
        should_warm_up = any(
            (
                settings.asr.preload_on_startup,
                settings.translation.preload_on_startup,
            )
        )
    if should_warm_up:
        service.warm_up_pipeline()
    return AppContext(settings=settings, service=service)
