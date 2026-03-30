from __future__ import annotations

import json
from typing import Iterable

from aiokafka import AIOKafkaProducer

from collector.config import KafkaConfig
from collector.events import build_raw_message_event
from collector.models import CollectedMessage


class KafkaRawSink:
    def __init__(self, config: KafkaConfig) -> None:
        self._config = config
        self._producer = AIOKafkaProducer(
            bootstrap_servers=config.bootstrap_servers,
            client_id=config.client_id,
            acks="all",
        )

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, items: Iterable[CollectedMessage]) -> int:
        count = 0
        for item in items:
            key, event = build_raw_message_event(item)
            await self._producer.send(
                self._config.topic,
                key=key.encode("utf-8"),
                value=json.dumps(event, ensure_ascii=False).encode("utf-8"),
            )
            count += 1

        await self._producer.flush()
        return count
