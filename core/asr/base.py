from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from schemas.runtime import ASRPreparationResult
from schemas.transcription import TranscriptionResult


class BaseASREngine(ABC):
    backend_name: str
    model_name: str

    def prepare(self) -> ASRPreparationResult:
        """Ensure model assets are available locally for later transcription"""
        raise NotImplementedError

    @abstractmethod
    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult:
        """Transcribe a local audio file into structured text"""
