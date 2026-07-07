"""RabbitMQ consumer — listens for news messages in a background thread."""

import threading
import json
import logging
import time
import queue

import pika
from pika.exceptions import AMQPConnectionError, AMQPChannelError

from config import RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_QUEUE

logger = logging.getLogger(__name__)

class MQConsumer:
    def __init__(self, message_queue: queue.Queue):
        self._running = False
        self._connection = None
        self._message_queue = message_queue
        self._consumer_thread: threading.Thread | None = None

    def stop(self):
        """Stop the consumer gracefully."""
        self._running = False
        self._connection.close()
        if self._consumer_thread:
            self._consumer_thread.join()


    def is_connected(self) -> bool:
        """Check if the RabbitMQ connection is alive."""
        try:
            return self._connection is not None and self._connection.is_open
        except Exception:
            return False

    def run(self):
        """Main loop for the consumer thread — connects, declares queue, and starts consuming."""
        
        logger.info(f"RabbitMQ consumer started on queue '{RABBITMQ_QUEUE}'")
        self._running = True
        while self._running:
            try:
                self._connection = self._connect()
                channel = self._connection.channel()
                channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
                channel.basic_qos(prefetch_count=1)
                channel.basic_consume(queue=RABBITMQ_QUEUE, on_message_callback=self._on_message)

                channel.start_consuming()

            except (AMQPConnectionError, AMQPChannelError, ConnectionError) as e:
                if self._running:
                    logger.warning(f"RabbitMQ connection lost: {e}. Reconnecting in 5s...")
                    time.sleep(5)
            except Exception:
                logger.exception("Unexpected error in consumer loop")
                if self._running:
                    time.sleep(5)
            finally:
                try:
                    if self._connection and self._connection.is_open:
                        self._connection.close()
                except Exception:
                    pass
        logger.info("RabbitMQ consumer stopped")

    def _on_message(self, ch, method, _properties, body):
        """Callback invoked when a message is received from the queue.

        Parses the raw JSON, normalises field names so downstream consumers
        receive a consistent schema regardless of the originating provider.
        """
        try:
            logger.debug("New message received")
            raw = body.decode("utf-8")
            msg = json.loads(raw)

            # -- field normalisation ------------------------------------
            # body (article text)  →  content
            if "body" in msg and "content" not in msg:
                msg["content"] = msg.pop("body")

            # time  →  timestamp
            if "time" in msg and "timestamp" not in msg:
                msg["timestamp"] = msg.pop("time")

            # relatedSymbols (list of {symbol, …})  →  symbol (first match)
            if "relatedSymbols" in msg and "symbol" not in msg:
                symbols = msg.pop("relatedSymbols")
                if isinstance(symbols, list) and symbols:
                    msg["symbol"] = symbols[0].get("symbol", "")
                elif isinstance(symbols, str):
                    msg["symbol"] = symbols
                else:
                    msg["symbol"] = ""

            # -----------------------------------------------------------
            normalised = json.dumps(msg, ensure_ascii=False).encode("utf-8")
            self._message_queue.put_nowait(normalised)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception:
            logger.exception("Error processing message — nacking without requeue")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def _connect(self) -> pika.BlockingConnection:
        """Establish a connection to RabbitMQ with retry."""
        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            heartbeat=30,
            connection_attempts=3,
            retry_delay=2.0,
        )
        return pika.BlockingConnection(params)
