from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter

from core.asr.base import BaseASREngine
from schemas.runtime import ASRPreparationResult
from schemas.transcription import TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)


class FasterWhisperASREngine(BaseASREngine):
    backend_name = "faster_whisper"

    def __init__(
        self,
        model_name: str,
        model_path: Path | None = None,
        device: str = "auto",
        compute_type: str = "int8",
        beam_size: int = 5,
        cpu_threads: int = 0,
        num_workers: int = 1,
        download_root: Path | None = None,
        local_files_only: bool = True,
    ) -> None:
        self.model_name = model_name
        self.model_path = model_path
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.cpu_threads = cpu_threads
        self.num_workers = num_workers
        self.download_root = download_root
        self.local_files_only = local_files_only
        self._model = None

    @property
    def model_source(self) -> str:
        if self.model_path is not None:
            return str(self.model_path)
        return self.model_name

    def _get_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as error:  # pragma: no cover - depends on optional runtime install
                raise RuntimeError(
                    "faster-whisper is not installed. Install project dependencies first."
                ) from error

            logger.info(
                "Initializing faster-whisper model_source=%s device=%s compute_type=%s "
                "local_files_only=%s download_root=%s",
                self.model_source,
                self.device,
                self.compute_type,
                self.local_files_only,
                self.download_root,
            )
            try:
                self._model = WhisperModel(
                    self.model_source,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=self.cpu_threads,
                    num_workers=self.num_workers,
                    download_root=(
                        str(self.download_root) if self.download_root is not None else None
                    ),
                    local_files_only=self.local_files_only,
                )
            except Exception as error:
                if self.local_files_only:
                    raise RuntimeError(
                        "Local speech model is not available. Run `voice-cli prepare-asr` once "
                        "with internet access or set `asr.model_path` to a local converted "
                        "faster-whisper model directory."
                    ) from error
                raise

        return self._model

    def prepare(self) -> ASRPreparationResult:
        self._get_model()
        return ASRPreparationResult(
            backend=self.backend_name,
            model_name=self.model_name,
            model_source=self.model_source,
            download_root=str(self.download_root) if self.download_root is not None else None,
            local_files_only=self.local_files_only,
            ready=True,
        )

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult:
        model = self._get_model()
        started_at = perf_counter()
        raw_segments, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=self.beam_size,
        )

        segments: list[TranscriptionSegment] = []
        text_chunks: list[str] = []

        for raw_segment in raw_segments:
            segment_text = raw_segment.text.strip()
            if segment_text:
                text_chunks.append(segment_text)
            segments.append(
                TranscriptionSegment(
                    start=float(raw_segment.start),
                    end=float(raw_segment.end),
                    text=segment_text,
                )
            )

        inference_seconds = perf_counter() - started_at

        return TranscriptionResult(
            transcript=" ".join(text_chunks).strip(),
            language=getattr(info, "language", None) or language,
            inference_seconds=inference_seconds,
            asr_backend=self.backend_name,
            model_name=self.model_name,
            segments=segments,
        )
