from __future__ import annotations
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from datetime import date
from collector.models import CollectedMessage


class Source(ABC):
    @abstractmethod
    async def iter_messages(
        self,
        channel: str,
        since: Optional[date],
        min_id_exclusive: Optional[int],
        limit: Optional[int],
    ) -> AsyncIterator[CollectedMessage]:
        raise NotImplementedError
