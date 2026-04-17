from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from rich.console import Console

from core.asr.base import BaseASREngine
from core.audio import (
    copy_audio_file,
    ensure_wav_path,
    get_audio_duration,
    get_audio_sample_rate,
    maybe_normalize_audio,
    save_uploaded_audio,
)
from core.language import normalize_language_code
from core.translation.base import BaseTranslationEngine
from schemas.config import AppSettings
from schemas.model import ModelRequest
from schemas.runtime import ModelPreparationResult, PipelinePreparationResult
from schemas.transcription import RunMetadata, TranscriptionRun, TranslationResult
from services.prepare_model import (
    build_skipped_preparation_result,
    prepare_configured_models,
    prepare_model,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunInputTarget:
    run_id: str
    timestamp: datetime
    run_dir: Path
    audio_path: Path


class TranscriptionService:
    def __init__(
        self,
        settings: AppSettings,
        asr_engine: BaseASREngine,
        translation_engine: BaseTranslationEngine,
        asr_request: ModelRequest,
        translation_request: ModelRequest,
    ) -> None:
        self.settings = settings
        self.asr_engine = asr_engine
        self.translation_engine = translation_engine
        self.asr_request = asr_request
        self.translation_request = translation_request

    def create_run_target(self) -> RunInputTarget:
        timestamp = datetime.now(UTC)
        run_id = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        run_dir = self.settings.storage.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        return RunInputTarget(
            run_id=run_id,
            timestamp=timestamp,
            run_dir=run_dir,
            audio_path=run_dir / "input.wav",
        )

    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        filename: str | None = None,
        language: str | None = None,
    ) -> TranscriptionRun:
        target = self.create_run_target()
        logger.info(
            "Saving uploaded audio for run_id=%s filename=%s",
            target.run_id,
            filename or "input.wav",
        )
        save_uploaded_audio(audio_bytes, target.audio_path)
        return self._process_run_audio(target, language=language)

    def transcribe_file(
        self,
        source_path: str | Path,
        language: str | None = None,
    ) -> TranscriptionRun:
        source = ensure_wav_path(Path(source_path))
        target = self.create_run_target()
        logger.info("Copying source audio for run_id=%s source=%s", target.run_id, source)
        copy_audio_file(source, target.audio_path)
        return self._process_run_audio(target, language=language)

    def transcribe_existing_run_audio(
        self,
        run_dir: str | Path,
        audio_path: str | Path,
        language: str | None = None,
    ) -> TranscriptionRun:
        resolved_run_dir = Path(run_dir).expanduser().resolve()
        resolved_audio_path = ensure_wav_path(Path(audio_path))
        if not resolved_audio_path.is_relative_to(resolved_run_dir):
            raise ValueError("Expected recorded audio to live inside the run directory.")
        target = RunInputTarget(
            run_id=resolved_run_dir.name,
            timestamp=datetime.now(UTC),
            run_dir=resolved_run_dir,
            audio_path=resolved_audio_path,
        )
        return self._process_run_audio(target, language=language)

    def transcribe_last(self, language: str | None = None) -> TranscriptionRun:
        latest_audio_path = self.get_last_audio_path()
        return self.transcribe_file(latest_audio_path, language=language)

    def prepare_asr_assets(
        self,
        *,
        force_download: bool = False,
        console: Console | None = None,
    ) -> ModelPreparationResult:
        logger.info(
            "Preparing ASR assets family=%s provider=%s model=%s",
            self.asr_request.descriptor.family,
            self.asr_request.descriptor.provider,
            self.asr_request.descriptor.model_name,
        )
        request = self.asr_request.model_copy(
            update={"force_download": force_download},
        )
        return prepare_model(request, console=console)

    def prepare_pipeline_assets(
        self,
        *,
        force_download: bool = False,
        console: Console | None = None,
    ) -> PipelinePreparationResult:
        logger.info("Preparing pipeline assets for configured speech components")
        return prepare_configured_models(
            self.settings,
            force_download=force_download,
            console=console,
        )

    def warm_up_asr(self) -> ModelPreparationResult:
        logger.info(
            "Warming up ASR family=%s provider=%s model=%s local_files_only=%s",
            self.asr_engine.family_name,
            self.asr_engine.provider_name,
            self.asr_engine.model_name,
            getattr(self.asr_engine, "local_files_only", None),
        )
        return self.asr_engine.prepare()

    def warm_up_pipeline(self) -> PipelinePreparationResult:
        components = [self.asr_engine.prepare()]
        if self.settings.translation.enabled:
            try:
                components.append(self.translation_engine.prepare())
            except RuntimeError as error:
                logger.warning("Skipping translation warm-up: %s", error)
                components.append(
                    build_skipped_preparation_result(
                        task="translation",
                        family=self.translation_request.descriptor.family,
                        provider=self.translation_request.descriptor.provider,
                        model_name=self.translation_request.descriptor.model_name,
                        model_source=self.translation_request.descriptor.model_name,
                        download_root=(
                            str(self.translation_request.descriptor.download_root)
                            if self.translation_request.descriptor.download_root is not None
                            else None
                        ),
                        local_files_only=self.translation_request.descriptor.local_files_only,
                        message=str(error),
                    )
                )
        return PipelinePreparationResult(components=components)

    def prepare_asr(self) -> ModelPreparationResult:
        return self.warm_up_asr()

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

    def _process_run_audio(
        self,
        target: RunInputTarget,
        *,
        language: str | None = None,
    ) -> TranscriptionRun:
        normalized_audio_path = maybe_normalize_audio(target.audio_path)
        effective_target = target
        if normalized_audio_path != target.audio_path:
            effective_target = RunInputTarget(
                run_id=target.run_id,
                timestamp=target.timestamp,
                run_dir=target.run_dir,
                audio_path=normalized_audio_path,
            )
        return self._transcribe_saved_audio(effective_target, language=language)

    def _transcribe_saved_audio(
        self,
        target: RunInputTarget,
        *,
        language: str | None = None,
    ) -> TranscriptionRun:
        effective_language = normalize_language_code(language) or self.settings.asr.language

        try:
            duration_seconds = get_audio_duration(target.audio_path)
            sample_rate = get_audio_sample_rate(target.audio_path)
            logger.info(
                "Starting transcription run_id=%s family=%s provider=%s model=%s",
                target.run_id,
                self.asr_engine.family_name,
                self.asr_engine.provider_name,
                self.asr_engine.model_name,
            )
            transcription = self.asr_engine.transcribe(
                target.audio_path,
                language=effective_language,
            )
            translation, translation_message = self._translate_transcript(
                transcription.transcript,
                transcription.language,
            )
            transcript_en = (
                translation.text if translation is not None else transcription.transcript
            )
        except Exception:
            logger.exception("Speech pipeline failed for run_id=%s", target.run_id)
            raise

        transcript_path = target.run_dir / "transcript.txt"
        transcript_en_path = target.run_dir / "transcript.en.txt"
        metadata_path = target.run_dir / "metadata.json"

        transcript_path.write_text(transcription.transcript + "\n", encoding="utf-8")
        transcript_en_path.write_text(transcript_en + "\n", encoding="utf-8")

        metadata = RunMetadata(
            id=target.run_id,
            timestamp=target.timestamp,
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            audio_path=str(target.audio_path.resolve()),
            language=transcription.language,
            transcript=transcription.transcript,
            transcript_en=transcript_en,
            target_language=(
                translation.target_language
                if translation is not None
                else self.translation_engine.normalize_language_code(
                    self.settings.translation.target_language
                )
                or "en"
            ),
            translation_status=(
                "translated"
                if translation is not None
                else ("skipped" if self.settings.translation.enabled else "disabled")
            ),
            translation_message=translation_message,
            inference_seconds=transcription.inference_seconds,
            asr_family=transcription.asr_family,
            asr_provider=transcription.asr_provider,
            asr_model_name=transcription.model_name,
            translation_family=translation.translation_family if translation else None,
            translation_provider=translation.translation_provider if translation else None,
            translation_model_name=translation.model_name if translation else None,
            translation_inference_seconds=translation.inference_seconds if translation else None,
        )
        metadata_path.write_text(
            json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "Completed speech pipeline run_id=%s duration=%.2fs asr=%.2fs translation=%s",
            target.run_id,
            duration_seconds,
            transcription.inference_seconds,
            f"{translation.inference_seconds:.2f}s" if translation is not None else "<disabled>",
        )

        return TranscriptionRun(
            run_dir=str(target.run_dir.resolve()),
            audio_path=str(target.audio_path.resolve()),
            transcript_path=str(transcript_path.resolve()),
            transcript_en_path=str(transcript_en_path.resolve()),
            metadata_path=str(metadata_path.resolve()),
            metadata=metadata,
        )

    def _translate_transcript(
        self,
        transcript: str,
        language: str | None,
    ) -> tuple[TranslationResult | None, str | None]:
        if not self.settings.translation.enabled:
            return None, None

        try:
            return (
                self.translation_engine.translate(
                    transcript,
                    source_language=language or self.settings.translation.source_language,
                    target_language=self.settings.translation.target_language,
                ),
                None,
            )
        except RuntimeError as error:
            logger.warning("Translation stage skipped: %s", error)
            return None, str(error)
