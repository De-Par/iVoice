from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from app.desktop_ui.qt import QObject, QThread, Slot
from app.desktop_ui.tasks import BackgroundTask
from schemas.command_run import CommandRun
from schemas.runtime import PipelinePreparationResult

if TYPE_CHECKING:
    from app.desktop_ui.window import VoiceDesktopWindow


class DesktopTranscriptionController(QObject):
    def __init__(self, window: VoiceDesktopWindow) -> None:
        super().__init__(window)
        self.window = window

    @Slot()
    def run_primary_action(self) -> None:
        if self.window._is_text_mode():
            self.normalize_current_text()
            return
        self.transcribe_current_audio()

    @Slot()
    def transcribe_current_audio(self) -> None:
        if self.window.context is None:
            self.window.show_info_dialog(
                "Initializing",
                "The local runtime is still starting. Please wait a moment.",
            )
            return
        if self.window._worker_kind == "transcribe":
            self.request_stop_transcription()
            return
        if self.window.current_audio_path is None or not self.window.current_audio_path.exists():
            self.window.show_info_dialog("No audio", "Record or open a WAV file first.")
            return
        if self.window._record_finalize_path is not None:
            self.window.show_info_dialog(
                "Audio is not ready",
                "The recording is still being finalized. Please wait a moment.",
            )
            return

        language = self.window.language_input.text().strip() or None
        audio_path = self.window.current_audio_path
        cold_start = getattr(self.window.context.service.asr_engine, "_model", None) is None
        self.run_background(
            fn=lambda: self.transcribe_with_auto_prepare(audio_path, language),
            on_success=self.show_transcription_result,
            busy_message="Preparing models" if cold_start else "Transcribing",
            kind="transcribe",
        )

    @Slot()
    def normalize_current_text(self) -> None:
        if self.window.context is None:
            self.window.show_info_dialog(
                "Initializing",
                "The local runtime is still starting. Please wait a moment.",
            )
            return
        if self.window._worker_kind == "transcribe":
            self.request_stop_transcription()
            return

        source_text = self.window.transcript_box.toPlainText().strip()
        if not source_text:
            self.window.show_info_dialog("No text", "Enter a command first.")
            return

        language = self.window.language_input.text().strip() or None
        self.run_background(
            fn=lambda: self.window.context.service.normalize_text_input(
                source_text,
                language=language,
            ),
            on_success=self.show_transcription_result,
            busy_message="Normalizing" if language else "Detecting language",
            kind="transcribe",
        )

    def run_background(
        self,
        fn: Callable[[], object],
        on_success: Callable[[object], None],
        busy_message: str,
        kind: str | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        if self.window._worker_thread is not None:
            self.window.show_info_dialog("Busy", "Another operation is already running.")
            return

        self.window._worker_kind = kind
        self.window._discard_worker_result = False
        self.window._show_notification(busy_message, tone="warning", animate=True, auto_hide_ms=0)
        self.window._set_controls_enabled(False)

        thread = QThread(self.window)
        worker = BackgroundTask(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_success)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(on_error or self.show_error)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self.clear_worker)

        self.window._worker_thread = thread
        self.window._worker = worker
        thread.start()

    @Slot(object)
    def show_transcription_result(self, result: object) -> None:
        prepare_payload = None
        if isinstance(result, dict):
            prepare_payload = result.get("prepare")
            if prepare_payload is not None:
                self.window.last_prepare_result = PipelinePreparationResult.model_validate(
                    prepare_payload
                )
            result = result["run"]

        if self.window._discard_worker_result:
            self.window._discard_worker_result = False
            self.window._hide_notification()
            self.window._refresh_details_panel()
            return

        self.window.last_run = CommandRun.model_validate(result)
        self.window._set_transcript_edit_mode(False)
        self.window.transcript_box.setPlainText(self.window.last_run.metadata.source_text)
        self.window.command_box.setPlainText(self.window.last_run.metadata.command_en)
        self.window.current_run_dir = Path(self.window.last_run.artifacts.run_dir)
        if self.window.last_run.metadata.source_modality == "text":
            self.window.source_mode_combo.setCurrentText("Text")
            self.window.audio_summary.setText("Direct text input mode.")
        else:
            self.window.source_mode_combo.setCurrentText("Audio")
        self.window._refresh_transcript_action_buttons()
        if prepare_payload is not None:
            skipped_components = [
                component
                for component in self.window.last_prepare_result.components
                if component.mode == "skipped"
            ]
            self.window._show_notification(
                "Check details" if skipped_components else "Models ready",
                tone="success",
                auto_hide_ms=1800,
            )
        else:
            self.window._show_notification("Done", tone="success", auto_hide_ms=1400)
        self.window._refresh_details_panel()

    @Slot(str)
    def show_error(self, message: str) -> None:
        self.window._show_notification("Task failed", tone="error", auto_hide_ms=0)
        self.window.show_error_dialog("Operation failed", message)

    @Slot()
    def clear_worker(self) -> None:
        self.window._worker_thread = None
        self.window._worker = None
        self.window._worker_kind = None
        self.window._set_controls_enabled(True)

    def request_stop_transcription(self) -> None:
        self.window._discard_worker_result = True
        self.window.transcribe_button.setEnabled(False)
        self.window._show_notification("Stopping", tone="warning", animate=True, auto_hide_ms=0)

    @Slot()
    def toggle_transcript_edit(self) -> None:
        if self.window.last_run is None:
            self.window.show_info_dialog("No source cmd", "Run audio or normalize text first.")
            return
        if self.window._is_editing_transcript:
            self.save_transcript_edits()
            return
        self.window._set_transcript_edit_mode(True)

    def save_transcript_edits(self) -> None:
        if self.window.context is None or self.window.last_run is None:
            return

        source_text = self.window.transcript_box.toPlainText().strip()
        if not source_text:
            self.window.show_info_dialog("Empty source cmd", "Source cmd cannot be empty.")
            return

        run_dir = Path(self.window.last_run.artifacts.run_dir)
        language = self.window.language_input.text().strip() or None

        self.run_background(
            fn=lambda: self.window.context.service.update_run_source_text(
                run_dir,
                source_text,
                language=language,
            ),
            on_success=self.show_saved_transcript_result,
            on_error=self.show_save_error,
            busy_message="Saving" if language else "Detecting language",
            kind="save_edit",
        )

    @Slot(object)
    def show_saved_transcript_result(self, result: object) -> None:
        self.window.last_run = CommandRun.model_validate(result)
        self.window._set_transcript_edit_mode(False)
        self.window.transcript_box.setPlainText(self.window.last_run.metadata.source_text)
        self.window.command_box.setPlainText(self.window.last_run.metadata.command_en)
        self.window._refresh_transcript_action_buttons()
        translation_status = self.window.last_run.metadata.translation_status
        translation_message = self.window.last_run.metadata.translation_message or ""
        if translation_status == "error":
            lowered_message = translation_message.lower()
            if "detect" in lowered_message or "ambiguous" in lowered_message:
                message = "Detection failed"
            elif "language pair" in lowered_message or "does not match" in lowered_message:
                message = "Unsupported language"
            else:
                message = "Translation failed"
            self.window._show_notification(message, tone="error", auto_hide_ms=3200)
        else:
            self.window._show_notification("Saved", tone="success", auto_hide_ms=1600)
        self.window._refresh_details_panel()

    @Slot(str)
    def show_save_error(self, message: str) -> None:
        pair_messages = (
            "language pair",
            "not supported",
            "Local translation model is not available",
        )
        if any(fragment in message for fragment in pair_messages):
            self.window._show_notification("Unsupported language", tone="error", auto_hide_ms=3200)
            return
        self.show_error(message)

    def transcribe_with_auto_prepare(
        self,
        audio_path: Path,
        language: str | None,
    ) -> dict[str, object]:
        if self.window.context is None:
            raise RuntimeError("Desktop runtime is not initialized yet.")
        try:
            if self.window.current_run_dir is not None and audio_path.is_relative_to(
                self.window.current_run_dir
            ):
                run = self.window.context.service.transcribe_existing_run_audio(
                    self.window.current_run_dir,
                    audio_path,
                    language=language,
                )
            else:
                run = self.window.context.service.transcribe_file(audio_path, language=language)
            return {"run": run}
        except RuntimeError as error:
            recoverable_errors = (
                "Local speech model is not available",
                "Local translation model is not available",
            )
            if not any(message in str(error) for message in recoverable_errors):
                raise

        prepare_result = self.window.context.service.prepare_pipeline_assets()
        if self.window.current_run_dir is not None and audio_path.is_relative_to(
            self.window.current_run_dir
        ):
            run = self.window.context.service.transcribe_existing_run_audio(
                self.window.current_run_dir,
                audio_path,
                language=language,
            )
        else:
            run = self.window.context.service.transcribe_file(audio_path, language=language)
        return {
            "run": run,
            "prepare": prepare_result,
        }
