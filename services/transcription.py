from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from rich.console import Console

from core.asr.base import BaseASREngine
from core.audio import (
    copy_audio_file,
    ensure_wav_path,
    get_audio_overview,
    maybe_normalize_audio,
    save_uploaded_audio,
)
from core.language import LanguageDetectionError, normalize_language_code
from core.translation.base import BaseTranslationEngine
from schemas.command import CommandNormalizationResult
from schemas.config import AppSettings
from schemas.model import ModelRequest
from schemas.runtime import ModelPreparationResult, PipelinePreparationResult
from schemas.transcription import RunArtifacts, RunMetadata, TranscriptionRun
from services.command_normalization import CommandNormalizationService
from services.prepare_model import (
    build_skipped_preparation_result,
    prepare_configured_models,
    prepare_model,
)
from services.run_service import RunInputTarget, RunService
from services.run_store import RunArtifactStore

logger = logging.getLogger(__name__)


class TranscriptionService:
    def __init__(
        self,
        settings: AppSettings,
        asr_engine: BaseASREngine,
        translation_engine: BaseTranslationEngine,
        asr_request: ModelRequest,
        translation_request: ModelRequest,
        command_normalization_service: CommandNormalizationService,
        run_store: RunArtifactStore,
        run_service: RunService,
    ) -> None:
        self.settings = settings
        self.asr_engine = asr_engine
        self.translation_engine = translation_engine
        self.asr_request = asr_request
        self.translation_request = translation_request
        self.command_normalization_service = command_normalization_service
        self.run_store = run_store
        self.run_service = run_service

    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        filename: str | None = None,
        language: str | None = None,
    ) -> TranscriptionRun:
        target = self.run_service.create_target()
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
        target = self.run_service.create_target()
        logger.info("Copying source audio for run_id=%s source=%s", target.run_id, source)
        copy_audio_file(source, target.audio_path)
        return self._process_run_audio(target, language=language)

    def transcribe_existing_run_audio(
        self,
        run_dir: str | Path,
        audio_path: str | Path,
        language: str | None = None,
    ) -> TranscriptionRun:
        target = self.run_service.build_existing_audio_target(run_dir, audio_path)
        return self._process_run_audio(target, language=language)

    def transcribe_last(self, language: str | None = None) -> TranscriptionRun:
        latest_audio_path = self.run_service.get_last_audio_path()
        return self.transcribe_file(latest_audio_path, language=language)

    def normalize_text_input(
        self,
        text: str,
        *,
        language: str | None = None,
    ) -> TranscriptionRun:
        target = self.run_service.create_target()
        return self._write_text_run(
            run_dir=target.run_dir,
            text=text,
            timestamp=target.timestamp,
            audio_path="",
            language=language,
            existing_metadata=None,
        )

    def normalize_command_text(
        self,
        text: str,
        *,
        language: str | None = None,
        fallback_language: str | None = None,
    ) -> CommandNormalizationResult:
        return self.command_normalization_service.normalize_command(
            text,
            modality="text",
            language=language,
            fallback_language=(
                fallback_language
                or self.settings.translation.source_language
                or self.settings.asr.language
            ),
            allow_detection=language is None,
            allow_segmented_fallback=language is None,
            source_if_explicit="explicit",
            source_if_fallback="config",
        )

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
                components.extend(self.command_normalization_service.warm_up_routes())
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

    def update_run_transcript(
        self,
        run_dir: str | Path,
        transcript: str,
        *,
        language: str | None = None,
    ) -> TranscriptionRun:
        resolved_run_dir = Path(run_dir).expanduser().resolve()
        existing_metadata = self.run_service.load_metadata(resolved_run_dir)
        return self._write_text_run(
            run_dir=resolved_run_dir,
            text=transcript,
            timestamp=existing_metadata.timestamp,
            audio_path=existing_metadata.audio_path,
            language=language,
            existing_metadata=existing_metadata,
        )

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
            duration_seconds, sample_rate = get_audio_overview(target.audio_path)
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
            normalization_result = self._normalize_audio_command(
                transcription.transcript,
                asr_language=transcription.language,
            )
            transcript_en = normalization_result.normalized.text
        except Exception:
            logger.exception("Speech pipeline failed for run_id=%s", target.run_id)
            raise

        artifacts = self._build_run_artifacts(
            run_dir=target.run_dir,
            audio_path=target.audio_path,
        )
        self.run_store.write_command_artifacts(
            artifacts=artifacts,
            source_text=transcription.transcript,
            normalized_text=transcript_en,
            normalization_result=normalization_result,
        )
        self.run_store.write_transcript(artifacts, transcription.transcript)
        self.run_store.write_transcript_en(artifacts, transcript_en)

        metadata = self._build_run_metadata(
            artifacts=artifacts,
            run_id=target.run_id,
            timestamp=target.timestamp,
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            source_text=transcription.transcript,
            source_modality="audio",
            transcript=transcription.transcript,
            transcript_en=transcript_en,
            normalization_result=normalization_result,
            inference_seconds=transcription.inference_seconds,
            asr_family=transcription.asr_family,
            asr_provider=transcription.asr_provider,
            asr_model_name=transcription.model_name,
        )
        self.run_store.write_metadata(artifacts, metadata)

        logger.info(
            "Completed speech pipeline run_id=%s duration=%.2fs asr=%.2fs translation=%s",
            target.run_id,
            duration_seconds,
            transcription.inference_seconds,
            (
                f"{normalization_result.normalized.translation_inference_seconds:.2f}s"
                if normalization_result.normalized.translation_inference_seconds is not None
                else f"<{normalization_result.normalized.status}>"
            ),
        )

        return self.run_store.build_run(artifacts, metadata)

    def _normalize_audio_command(
        self,
        transcript: str,
        *,
        asr_language: str | None,
    ) -> CommandNormalizationResult:
        try:
            return self.command_normalization_service.normalize_command(
                transcript,
                modality="audio",
                language=asr_language,
                fallback_language=self.settings.translation.source_language,
                allow_detection=False,
                allow_segmented_fallback=True,
                source_if_explicit="asr",
                source_if_fallback="config",
            )
        except RuntimeError as error:
            logger.warning("Command normalization stage skipped: %s", error)
            return self.command_normalization_service.build_error_result(
                transcript,
                modality="audio",
                message=str(error),
                normalized_text=transcript,
                language=asr_language,
                language_source="asr" if asr_language else "config",
            )

    def _normalize_manual_command(
        self,
        transcript: str,
        *,
        explicit_language: str | None,
        fallback_language: str | None,
        existing_command_en: str,
    ) -> CommandNormalizationResult:
        try:
            return self.command_normalization_service.normalize_command(
                transcript,
                modality="text",
                language=explicit_language,
                fallback_language=fallback_language,
                allow_detection=explicit_language is None,
                source_if_explicit="explicit",
                source_if_fallback="config",
            )
        except LanguageDetectionError as error:
            return self.command_normalization_service.build_error_result(
                transcript,
                modality="text",
                message=str(error),
                normalized_text=existing_command_en,
                language=None,
                language_source="unknown",
            )
        except RuntimeError as error:
            return self.command_normalization_service.build_error_result(
                transcript,
                modality="text",
                message=str(error),
                normalized_text=existing_command_en,
                language=explicit_language or fallback_language,
                language_source="explicit" if explicit_language else "config",
            )

    def _write_text_run(
        self,
        *,
        run_dir: Path,
        text: str,
        timestamp: datetime,
        audio_path: str,
        language: str | None,
        existing_metadata: RunMetadata | None,
    ) -> TranscriptionRun:
        artifacts = self._build_run_artifacts(
            run_dir=run_dir,
            audio_path=audio_path,
        )

        normalized_transcript = text.strip()
        if not normalized_transcript:
            raise ValueError("Transcript cannot be empty.")

        self.run_store.write_transcript(artifacts, normalized_transcript)

        explicit_language = normalize_language_code(language)
        fallback_language = (
            normalize_language_code(existing_metadata.language)
            if existing_metadata is not None and existing_metadata.language is not None
            else self.settings.translation.source_language or self.settings.asr.language
        )
        normalization_result = self._normalize_manual_command(
            normalized_transcript,
            explicit_language=explicit_language,
            fallback_language=fallback_language,
            existing_command_en=(
                existing_metadata.command_en
                if existing_metadata is not None and existing_metadata.command_en
                else (
                    existing_metadata.transcript_en
                    if existing_metadata is not None
                    else normalized_transcript
                )
            ),
        )
        self.run_store.write_command_artifacts(
            artifacts=artifacts,
            source_text=normalized_transcript,
            normalized_text=normalization_result.normalized.text,
            normalization_result=normalization_result,
        )
        transcript_en = normalization_result.normalized.text
        should_write_normalized = (
            normalization_result.normalized.status != "error"
            or not self.run_store.transcript_en_exists(artifacts)
        )
        if should_write_normalized:
            self.run_store.write_transcript_en(artifacts, transcript_en)

        existing_id = existing_metadata.id if existing_metadata is not None else run_dir.name
        updated_metadata = self._build_run_metadata(
            artifacts=artifacts,
            run_id=existing_id,
            timestamp=timestamp,
            duration_seconds=0.0,
            sample_rate=1,
            source_text=normalized_transcript,
            source_modality="text",
            transcript=normalized_transcript,
            transcript_en=transcript_en,
            normalization_result=normalization_result,
            inference_seconds=0.0,
            asr_family=self.asr_request.descriptor.family,
            asr_provider=self.asr_request.descriptor.provider,
            asr_model_name=self.asr_request.descriptor.model_name,
            existing_metadata=existing_metadata,
        )
        self.run_store.write_metadata(artifacts, updated_metadata)

        return self.run_store.build_run(artifacts, updated_metadata)

    def _build_run_artifacts(
        self,
        *,
        run_dir: Path,
        audio_path: str | Path,
    ) -> RunArtifacts:
        return self.run_store.build_artifacts(
            run_dir=run_dir,
            audio_path=audio_path,
        )

    def _build_normalization_metadata_fields(
        self,
        *,
        artifacts: RunArtifacts,
        source_text: str,
        source_modality: str,
        transcript: str,
        transcript_en: str,
        normalization_result: CommandNormalizationResult,
    ) -> dict[str, object]:
        return {
            "source_text": source_text,
            "source_modality": source_modality,
            "language": normalization_result.source.language,
            "language_source": normalization_result.source.language_source,
            "transcript": transcript,
            "transcript_en": transcript_en,
            "command_en": normalization_result.normalized.text,
            "normalization_spans_path": artifacts.normalization_spans_path,
            "normalization_span_count": len(normalization_result.spans),
            "target_language": normalization_result.normalized.target_language,
            "normalization_status": normalization_result.normalized.status,
            "normalization_message": normalization_result.normalized.message,
            "translation_status": normalization_result.normalized.status,
            "translation_message": normalization_result.normalized.message,
            "translation_family": normalization_result.normalized.translation_family,
            "translation_provider": normalization_result.normalized.translation_provider,
            "translation_model_name": normalization_result.normalized.translation_model_name,
            "translation_inference_seconds": (
                normalization_result.normalized.translation_inference_seconds
            ),
        }

    def _build_run_metadata(
        self,
        *,
        artifacts: RunArtifacts,
        run_id: str,
        timestamp: datetime,
        duration_seconds: float,
        sample_rate: int,
        source_text: str,
        source_modality: str,
        transcript: str,
        transcript_en: str,
        normalization_result: CommandNormalizationResult,
        inference_seconds: float,
        asr_family: str,
        asr_provider: str,
        asr_model_name: str,
        existing_metadata: RunMetadata | None = None,
    ) -> RunMetadata:
        payload = {
            "id": run_id,
            "timestamp": timestamp,
            "duration_seconds": duration_seconds,
            "sample_rate": sample_rate,
            "audio_path": artifacts.audio_path,
            "inference_seconds": inference_seconds,
            "asr_family": asr_family,
            "asr_provider": asr_provider,
            "asr_model_name": asr_model_name,
            **self._build_normalization_metadata_fields(
                artifacts=artifacts,
                source_text=source_text,
                source_modality=source_modality,
                transcript=transcript,
                transcript_en=transcript_en,
                normalization_result=normalization_result,
            ),
        }
        if existing_metadata is not None:
            return existing_metadata.model_copy(update=payload)
        return RunMetadata(**payload)
