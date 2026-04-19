from __future__ import annotations

from core.pcs.base import BasePCSEngine
from schemas.command import PCSNormalizationResult
from schemas.runtime import ModelPreparationResult


class IdentityPCSEngine(BasePCSEngine):
    family_name = "identity"
    provider_name = "identity"

    def __init__(self, model_name: str = "identity") -> None:
        self.model_name = model_name

    def prepare(self) -> ModelPreparationResult:
        return ModelPreparationResult(
            task="pcs",
            family=self.family_name,
            provider=self.provider_name,
            model_name=self.model_name,
            model_source=self.model_name,
            local_files_only=True,
            ready=True,
            mode="identity",
        )

    def normalize_text(self, text: str) -> PCSNormalizationResult:
        return PCSNormalizationResult(
            text=text,
            status="skipped",
            message="PCS post-processing is disabled.",
            pcs_family=self.family_name,
            pcs_provider=self.provider_name,
            pcs_model_name=self.model_name,
        )
