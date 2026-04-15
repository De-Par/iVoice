from __future__ import annotations

import logging
import warnings
from contextlib import contextmanager

from huggingface_hub import hf_hub_download
from huggingface_hub.utils import (
    are_progress_bars_disabled,
    disable_progress_bars,
    enable_progress_bars,
)
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from schemas.config import ASRSettings
from schemas.runtime import ASRPreparationResult

FASTER_WHISPER_REQUIRED_FILES = (
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
)


@contextmanager
def suppress_hf_transfer_logs():
    targets = [
        logging.getLogger("httpx"),
        logging.getLogger("huggingface_hub"),
        logging.getLogger("huggingface_hub.file_download"),
        logging.getLogger("huggingface_hub.utils._http"),
    ]
    previous_levels = [target.level for target in targets]
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="You are sending unauthenticated requests to the HF Hub.*",
            )
            for target in targets:
                target.setLevel(logging.WARNING)
            yield
    finally:
        for target, level in zip(targets, previous_levels, strict=False):
            target.setLevel(level)


@contextmanager
def suppress_hf_progress_bars():
    were_disabled = are_progress_bars_disabled()
    try:
        disable_progress_bars()
        yield
    finally:
        if not were_disabled:
            enable_progress_bars()


def format_bytes(value: int) -> str:
    size = float(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{value} B"


class FasterWhisperAssetPreparer:
    def __init__(self, settings: ASRSettings, console: Console | None = None) -> None:
        self.settings = settings
        self.console = console or Console()

    @property
    def repo_id(self) -> str:
        return f"Systran/faster-whisper-{self.settings.model_name}"

    def prepare(self, force_download: bool = False) -> ASRPreparationResult:
        if self.settings.model_path is not None:
            if not self.settings.model_path.exists():
                raise FileNotFoundError(
                    f"Configured ASR model_path does not exist: {self.settings.model_path}"
                )
            download_root = (
                str(self.settings.download_root) if self.settings.download_root else None
            )
            return ASRPreparationResult(
                backend="faster_whisper",
                model_name=self.settings.model_name,
                model_source=str(self.settings.model_path),
                download_root=download_root,
                local_files_only=True,
                ready=True,
                downloaded_files=0,
                total_files=0,
                downloaded_bytes=0,
                total_bytes=0,
                mode="local_path",
            )

        if self.settings.download_root is None:
            raise ValueError("ASR download_root must be configured for model preparation.")

        self.settings.download_root.mkdir(parents=True, exist_ok=True)
        file_infos = []
        with suppress_hf_transfer_logs(), suppress_hf_progress_bars():
            for filename in FASTER_WHISPER_REQUIRED_FILES:
                info = hf_hub_download(
                    repo_id=self.repo_id,
                    filename=filename,
                    cache_dir=self.settings.download_root,
                    local_files_only=False,
                    dry_run=True,
                )
                file_infos.append(info)

        total_bytes = sum(file_info.file_size for file_info in file_infos)
        downloadable_infos = [
            file_info for file_info in file_infos if file_info.will_download or force_download
        ]
        bytes_to_download = sum(file_info.file_size for file_info in downloadable_infos)

        if not downloadable_infos and not force_download:
            self.console.print("[green]ASR model is already cached locally.[/green]")
            return ASRPreparationResult(
                backend="faster_whisper",
                model_name=self.settings.model_name,
                model_source=self.settings.model_name,
                download_root=str(self.settings.download_root),
                local_files_only=True,
                ready=True,
                downloaded_files=0,
                total_files=len(file_infos),
                downloaded_bytes=0,
                total_bytes=total_bytes,
                mode="cached",
            )

        self.console.print(f"Preparing [bold]{self.settings.model_name}[/bold]")
        self.console.print(f"Target cache: `{self.settings.download_root}`")
        self.console.print(
            f"{len(downloadable_infos)} file(s), {format_bytes(bytes_to_download)} to download."
        )

        progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(bar_width=32),
            console=self.console,
            transient=True,
        )

        with progress, suppress_hf_transfer_logs(), suppress_hf_progress_bars():
            overall_task = progress.add_task("Preparing files", total=len(downloadable_infos))
            current_task = progress.add_task("Waiting...", total=None)

            for index, file_info in enumerate(downloadable_infos, start=1):
                progress.update(
                    current_task,
                    description=(
                        f"[cyan]{index}/{len(downloadable_infos)}[/cyan] "
                        f"{file_info.filename} ({format_bytes(file_info.file_size)})"
                    ),
                    total=None,
                )
                hf_hub_download(
                    repo_id=self.repo_id,
                    filename=file_info.filename,
                    cache_dir=self.settings.download_root,
                    local_files_only=False,
                    force_download=force_download,
                )
                progress.advance(overall_task, 1)

            progress.update(
                current_task,
                description="[green]Download complete[/green]",
                total=1,
                completed=1,
            )

        return ASRPreparationResult(
            backend="faster_whisper",
            model_name=self.settings.model_name,
            model_source=self.settings.model_name,
            download_root=str(self.settings.download_root),
            local_files_only=True,
            ready=True,
            downloaded_files=len(downloadable_infos),
            total_files=len(file_infos),
            downloaded_bytes=bytes_to_download,
            total_bytes=total_bytes,
            mode="downloaded" if downloadable_infos else "cached",
        )
