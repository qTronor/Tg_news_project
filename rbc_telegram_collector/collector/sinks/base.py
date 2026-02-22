from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterable
from collector.models import CollectedMessage


class Sink(ABC):
    @abstractmethod
    def write(self, items: Iterable[CollectedMessage]) -> int:
        """Return number of written items."""
        raise NotImplementedError
