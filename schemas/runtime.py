from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ASRPreparationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    backend: str
    model_name: str
    model_source: str
    download_root: str | None = None
    local_files_only: bool
    ready: bool = True
    downloaded_files: int = 0
    total_files: int = 0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    mode: str = "verified"
