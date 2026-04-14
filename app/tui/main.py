from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.settings import load_settings
from schemas.config import AppSettings
from schemas.runtime import ASRPreparationResult
from schemas.transcription import TranscriptionRun
from services.asr_assets import FasterWhisperAssetPreparer, format_bytes
from services.bootstrap import build_app_context

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


def _render_result(result: TranscriptionRun) -> None:
    table = Table(show_header=False)
    table.add_row("Run ID", result.metadata.id)
    table.add_row("Timestamp", result.metadata.timestamp.isoformat())
    table.add_row("Transcript", result.metadata.transcript or "<empty>")
    table.add_row("Language", result.metadata.language or "<unknown>")
    table.add_row("Duration", f"{result.metadata.duration_seconds:.2f}s")
    table.add_row("Sample rate", str(result.metadata.sample_rate))
    table.add_row("Inference", f"{result.metadata.inference_seconds:.2f}s")
    table.add_row("Run dir", result.run_dir)
    console.print(Panel(table, title="Transcription Result"))


def _render_prepare_result(result: ASRPreparationResult) -> None:
    table = Table(show_header=False)
    table.add_row("Mode", result.mode)
    table.add_row("Backend", result.backend)
    table.add_row("Model", result.model_name)
    table.add_row("Model source", result.model_source)
    table.add_row("Download root", result.download_root or "<none>")
    table.add_row("Files", f"{result.downloaded_files}/{result.total_files}")
    table.add_row("Downloaded", format_bytes(result.downloaded_bytes))
    table.add_row("Total size", format_bytes(result.total_bytes))
    table.add_row("Offline ready", str(result.local_files_only))
    table.add_row("Ready", str(result.ready))
    console.print(Panel(table, title="ASR Preparation"))


def _load_settings() -> AppSettings:
    return load_settings()


@app.command("transcribe-file")
def transcribe_file(
    path: Path,
    language: str | None = typer.Option(default=None, help="Optional language override."),
) -> None:
    """Transcribe a local WAV file and persist run artifacts"""

    try:
        result = build_app_context().service.transcribe_file(path, language=language)
    except Exception as error:
        console.print(f"[red]Transcription failed:[/red] {error}")
        raise typer.Exit(code=1) from error

    _render_result(result)


@app.command("transcribe-last")
def transcribe_last(
    language: str | None = typer.Option(default=None, help="Optional language override."),
) -> None:
    """Reuse the audio file from the latest run and transcribe it again"""

    try:
        result = build_app_context().service.transcribe_last(language=language)
    except Exception as error:
        console.print(f"[red]Transcription failed:[/red] {error}")
        raise typer.Exit(code=1) from error

    _render_result(result)


@app.command("prepare-asr")
def prepare_asr(
    force: bool = typer.Option(False, "--force", help="Redownload files even if they are cached."),
) -> None:
    """Download or verify ASR model assets locally for offline runtime use"""

    try:
        settings = _load_settings()
        preparer = FasterWhisperAssetPreparer(settings.asr, console=console)
        result = preparer.prepare(force_download=force)
    except Exception as error:
        console.print(f"[red]ASR preparation failed:[/red] {error}")
        raise typer.Exit(code=1) from error

    _render_prepare_result(result)


def run() -> None:
    app()


if __name__ == "__main__":
    run()
