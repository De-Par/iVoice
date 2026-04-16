from __future__ import annotations

from abc import ABC, abstractmethod


class BaseStyleParser(ABC):
    @abstractmethod
    def parse(self, instruction: str) -> dict:
        """Parse natural-language synthesis instructions into structured speech controls."""
