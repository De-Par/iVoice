from __future__ import annotations

import os
import tomllib
from pathlib import Path

from schemas.config import AppSettings, ASRSettings, StorageSettings

DEFAULT_CONFIG_PATH = Path("config.toml")


def _resolve_storage(base_dir: Path, storage: StorageSettings) -> StorageSettings:
    return storage.model_copy(
        update={
            "runs_dir": (base_dir / storage.runs_dir).resolve()
            if not storage.runs_dir.is_absolute()
            else storage.runs_dir,
            "data_dir": (base_dir / storage.data_dir).resolve()
            if not storage.data_dir.is_absolute()
            else storage.data_dir,
            "samples_dir": (base_dir / storage.samples_dir).resolve()
            if not storage.samples_dir.is_absolute()
            else storage.samples_dir,
        }
    )


def _resolve_asr_paths(base_dir: Path, asr: ASRSettings) -> ASRSettings:
    return asr.model_copy(
        update={
            "model_path": (base_dir / asr.model_path).resolve()
            if asr.model_path is not None and not asr.model_path.is_absolute()
            else asr.model_path,
            "download_root": (base_dir / asr.download_root).resolve()
            if asr.download_root is not None and not asr.download_root.is_absolute()
            else asr.download_root,
        }
    )


def load_settings(config_path: str | Path | None = None) -> AppSettings:
    raw_path = Path(config_path or os.getenv("VOICE_APP_CONFIG", DEFAULT_CONFIG_PATH))
    config_file = raw_path.resolve()
    payload: dict = {}

    if config_file.exists():
        payload = tomllib.loads(config_file.read_text(encoding="utf-8"))
        base_dir = config_file.parent
    else:
        base_dir = Path.cwd()

    settings = AppSettings.model_validate(payload)
    resolved_storage = _resolve_storage(base_dir, settings.storage)
    resolved_asr = _resolve_asr_paths(base_dir, settings.asr)

    for directory in (
        resolved_storage.runs_dir,
        resolved_storage.data_dir,
        resolved_storage.samples_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    if resolved_asr.download_root is not None:
        resolved_asr.download_root.mkdir(parents=True, exist_ok=True)

    return settings.model_copy(update={"storage": resolved_storage, "asr": resolved_asr})
