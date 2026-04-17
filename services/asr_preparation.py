from __future__ import annotations

from rich.console import Console

from schemas.config import AppSettings
from schemas.runtime import ASRPreparationResult
from services.asr_assets import FasterWhisperAssetPreparer


def prepare_asr_assets(
    settings: AppSettings,
    *,
    force_download: bool = False,
    console: Console | None = None,
) -> ASRPreparationResult:
    preparer = FasterWhisperAssetPreparer(settings.asr, console=console)
    return preparer.prepare(force_download=force_download)
