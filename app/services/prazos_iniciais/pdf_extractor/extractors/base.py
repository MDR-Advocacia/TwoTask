"""Interface comum dos extractors específicos por template."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.prazos_iniciais.pdf_extractor import ExtractionResult


class BaseExtractor(ABC):
    """Cada template (PJe TJBA, eSAJ TJSP, ...) implementa um extractor."""

    name: str = "base"

    @abstractmethod
    def extract(self, pages: List[str]) -> "ExtractionResult":
        """Recebe texto por página, devolve ExtractionResult preenchido."""
        ...
