from __future__ import annotations

from abc import ABC, abstractmethod


class BaseStyleParser(ABC):
    @abstractmethod
    def parse(self, instruction: str) -> dict:
        """Parse future expressive speech/style instructions into structured controls"""

