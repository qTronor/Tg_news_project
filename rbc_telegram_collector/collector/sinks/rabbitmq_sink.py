"""
Пример реализации Sink для отправки сообщений в RabbitMQ.

Для использования добавьте в requirements.txt:
    pika>=1.3.0

И в config.yaml добавьте секцию broker.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, Optional

try:
    import pika
    from pika.exceptions import AMQPConnectionError
except ImportError:
    pika = None
    AMQPConnectionError = Exception

from collector.models import CollectedMessage
from collector.sinks.base import Sink


class RabbitMQSink(Sink):
    """
    Sink для отправки сообщений в RabbitMQ.
    
    Конфигурация:
        broker:
          type: "rabbitmq"
          host: "localhost"
          port: 5672
          username: "guest"
          password: "guest"
          exchange: "telegram_messages"
          routing_key_template: "{channel}"  # или фиксированное значение
    """
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 5672,
        username: Optional[str] = None,
        password: Optional[str] = None,
        exchange: str = "telegram_messages",
        routing_key_template: str = "{channel}",
        virtual_host: str = "/",
    ):
        if pika is None:
            raise ImportError("pika is required for RabbitMQSink. Install with: pip install pika")
        
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.exchange = exchange
        self.routing_key_template = routing_key_template
        self.virtual_host = virtual_host
        
        self.logger = logging.getLogger(__name__)
        self._connection: Optional[pika.BlockingConnection] = None
        self._channel: Optional[pika.channel.Channel] = None
    
    def _connect(self) -> None:
        """Установить соединение с RabbitMQ."""
        credentials = None
        if self.username and self.password:
            credentials = pika.PlainCredentials(self.username, self.password)
        
        parameters = pika.ConnectionParameters(
            host=self.host,
            port=self.port,
            virtual_host=self.virtual_host,
            credentials=credentials,
        )
        
        try:
            self._connection = pika.BlockingConnection(parameters)
            self._channel = self._connection.channel()
            # Объявляем exchange (если не существует, создастся)
            self._channel.exchange_declare(
                exchange=self.exchange,
                exchange_type="topic",  # или "direct", "fanout"
                durable=True,
            )
            self.logger.info(f"Connected to RabbitMQ at {self.host}:{self.port}")
        except AMQPConnectionError as e:
            self.logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise
    
    def _disconnect(self) -> None:
        """Закрыть соединение с RabbitMQ."""
        if self._channel and not self._channel.is_closed:
            self._channel.close()
        if self._connection and not self._connection.is_closed:
            self._connection.close()
        self.logger.info("Disconnected from RabbitMQ")
    
    def write(self, items: Iterable[CollectedMessage]) -> int:
        """Отправить сообщения в RabbitMQ."""
        if self._connection is None or self._connection.is_closed:
            self._connect()
        
        count = 0
        try:
            for item in items:
                # Сериализуем сообщение в JSON
                message_body = json.dumps(item.to_dict(), ensure_ascii=False, default=str)
                
                # Формируем routing key (например, "rbc_news" или "telegram.rbc_news")
                routing_key = self.routing_key_template.format(
                    channel=item.channel,
                    source=item.source,
                )
                
                # Публикуем сообщение
                self._channel.basic_publish(
                    exchange=self.exchange,
                    routing_key=routing_key,
                    body=message_body.encode("utf-8"),
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # Persistent message
                        content_type="application/json",
                        headers={
                            "source": item.source,
                            "channel": item.channel,
                            "message_id": item.message_id,
                        },
                    ),
                )
                count += 1
            
            self.logger.info(f"Published {count} messages to RabbitMQ exchange={self.exchange}")
            return count
        
        except Exception as e:
            self.logger.error(f"Error publishing to RabbitMQ: {e}")
            # Переподключаемся при следующем вызове
            self._disconnect()
            raise
    
    def __enter__(self):
        """Context manager entry."""
        self._connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self._disconnect()


