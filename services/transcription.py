from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from core.asr.base import BaseASREngine
from core.audio import (
    copy_audio_file,
    get_audio_duration,
    get_audio_sample_rate,
    maybe_normalize_audio,
    save_uploaded_audio,
)
from schemas.config import AppSettings
from schemas.runtime import ASRPreparationResult
from schemas.transcription import RunMetadata, TranscriptionRun

logger = logging.getLogger(__name__)


class TranscriptionService:
    def __init__(self, settings: AppSettings, asr_engine: BaseASREngine) -> None:
        self.settings = settings
        self.asr_engine = asr_engine

    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        filename: str | None = None,
        language: str | None = None,
    ) -> TranscriptionRun:
        run_id, timestamp, run_dir = self._create_run_dir()
        audio_path = run_dir / "input.wav"

        logger.info(
            "Saving uploaded audio for run_id=%s filename=%s",
            run_id,
            filename or "input.wav",
        )
        save_uploaded_audio(audio_bytes, audio_path)
        normalized_audio_path = maybe_normalize_audio(audio_path)
        return self._transcribe_saved_audio(
            run_id=run_id,
            timestamp=timestamp,
            run_dir=run_dir,
            audio_path=normalized_audio_path,
            language=language,
        )

    def transcribe_file(
        self,
        source_path: str | Path,
        language: str | None = None,
    ) -> TranscriptionRun:
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"Audio file not found: {source}")
        if source.suffix.lower() != ".wav":
            raise ValueError("Only WAV files are supported right now.")

        run_id, timestamp, run_dir = self._create_run_dir()
        audio_path = run_dir / "input.wav"

        logger.info("Copying source audio for run_id=%s source=%s", run_id, source)
        copy_audio_file(source, audio_path)
        normalized_audio_path = maybe_normalize_audio(audio_path)
        return self._transcribe_saved_audio(
            run_id=run_id,
            timestamp=timestamp,
            run_dir=run_dir,
            audio_path=normalized_audio_path,
            language=language,
        )

    def transcribe_last(self, language: str | None = None) -> TranscriptionRun:
        latest_audio_path = self.get_last_audio_path()
        return self.transcribe_file(latest_audio_path, language=language)

    def prepare_asr(self) -> ASRPreparationResult:
        logger.info(
            "Preparing ASR backend=%s model=%s local_files_only=%s",
            self.asr_engine.backend_name,
            self.asr_engine.model_name,
            getattr(self.asr_engine, "local_files_only", None),
        )
        return self.asr_engine.prepare()

    def get_last_audio_path(self) -> Path:
        run_dirs = sorted(
            [path for path in self.settings.storage.runs_dir.iterdir() if path.is_dir()],
            key=lambda path: path.name,
        )
        if not run_dirs:
            raise FileNotFoundError("No runs available in runs directory.")

        latest_run_dir = run_dirs[-1]
        audio_path = latest_run_dir / "input.wav"
        if not audio_path.exists():
            raise FileNotFoundError(f"No input.wav found in latest run: {latest_run_dir}")
        return audio_path

    def _create_run_dir(self) -> tuple[str, datetime, Path]:
        timestamp = datetime.now(UTC)
        run_id = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        run_dir = self.settings.storage.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_id, timestamp, run_dir

    def _transcribe_saved_audio(
        self,
        run_id: str,
        timestamp: datetime,
        run_dir: Path,
        audio_path: Path,
        language: str | None = None,
    ) -> TranscriptionRun:
        effective_language = language or self.settings.asr.language

        try:
            duration_seconds = get_audio_duration(audio_path)
            sample_rate = get_audio_sample_rate(audio_path)
            logger.info(
                "Starting transcription run_id=%s backend=%s model=%s",
                run_id,
                self.asr_engine.backend_name,
                self.asr_engine.model_name,
            )
            transcription = self.asr_engine.transcribe(audio_path, language=effective_language)
        except Exception:
            logger.exception("Transcription failed for run_id=%s", run_id)
            raise

        transcript_path = run_dir / "transcript.txt"
        metadata_path = run_dir / "metadata.json"

        transcript_path.write_text(transcription.transcript + "\n", encoding="utf-8")

        metadata = RunMetadata(
            id=run_id,
            timestamp=timestamp,
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            audio_path=str(audio_path.resolve()),
            language=transcription.language,
            transcript=transcription.transcript,
            inference_seconds=transcription.inference_seconds,
            asr_backend=transcription.asr_backend,
            model_name=transcription.model_name,
        )
        metadata_path.write_text(
            json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "Completed transcription run_id=%s duration=%.2fs inference=%.2fs",
            run_id,
            duration_seconds,
            transcription.inference_seconds,
        )

        return TranscriptionRun(
            run_dir=str(run_dir.resolve()),
            audio_path=str(audio_path.resolve()),
            transcript_path=str(transcript_path.resolve()),
            metadata_path=str(metadata_path.resolve()),
            metadata=metadata,
        )
