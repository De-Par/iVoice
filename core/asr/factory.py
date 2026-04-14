from __future__ import annotations

from core.asr.base import BaseASREngine
from core.asr.faster_whisper_engine import FasterWhisperASREngine
from schemas.config import AppSettings


def build_asr_engine(settings: AppSettings) -> BaseASREngine:
    backend = settings.asr.backend.lower()

    if backend == "faster_whisper":
        return FasterWhisperASREngine(
            model_name=settings.asr.model_name,
            model_path=settings.asr.model_path,
            device=settings.asr.device,
            compute_type=settings.asr.compute_type,
            beam_size=settings.asr.beam_size,
            cpu_threads=settings.asr.cpu_threads,
            num_workers=settings.asr.num_workers,
            download_root=settings.asr.download_root,
            local_files_only=settings.asr.local_files_only,
        )

    raise ValueError(f"Unsupported ASR backend: {settings.asr.backend}")
