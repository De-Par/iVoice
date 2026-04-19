from __future__ import annotations

from abc import ABC, abstractmethod

from schemas.command import PCSNormalizationResult
from schemas.runtime import ModelPreparationResult


class BasePCSEngine(ABC):
    family_name: str
    provider_name: str
    model_name: str

    def prepare(self) -> ModelPreparationResult:
        raise NotImplementedError

    @abstractmethod
    def normalize_text(self, text: str) -> PCSNormalizationResult:
        """Restore punctuation, casing, and lightweight command formatting"""
