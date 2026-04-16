from __future__ import annotations

from abc import ABC, abstractmethod


class BaseTTSEngine(ABC):
    backend_name: str
    model_name: str

    @abstractmethod
    def synthesize(self, text: str, **kwargs) -> dict:
        """Generate speech artifacts from text and optional structured style controls."""
