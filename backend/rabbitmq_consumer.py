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
        self._listening_enabled = False  # Default: NOT listening — user must click Start
        self._connection = None
        self._channel = None
        self._message_queue = message_queue
        self._consumer_thread: threading.Thread | None = None

    def start(self):
        """Enable message consumption from RabbitMQ."""
        self._listening_enabled = True
        logger.info("MQ consumption STARTED by user")
        # Interrupt active consuming so the loop re-checks the flag
        if self._connection and self._connection.is_open and self._channel:
            try:
                self._connection.add_callback_threadsafe(self._channel.stop_consuming)
            except Exception:
                pass

    def stop(self):
        """Disable message consumption (pause without disconnect)."""
        self._listening_enabled = False
        logger.info("MQ consumption STOPPED by user")
        if self._connection and self._connection.is_open and self._channel:
            try:
                self._connection.add_callback_threadsafe(self._channel.stop_consuming)
            except Exception:
                pass

    def is_listening(self) -> bool:
        """Check whether consumer is actively listening for messages."""
        return self._listening_enabled

    def shutdown(self):
        """Fully stop the consumer and close connection (used on app shutdown)."""
        self._running = False
        self._listening_enabled = False
        try:
            if self._connection and self._connection.is_open:
                self._connection.close()
        except Exception:
            pass

    def is_connected(self) -> bool:
        """Check if the RabbitMQ connection is alive."""
        try:
            return self._connection is not None and self._connection.is_open
        except Exception:
            return False

    def run(self):
        """Main loop for the consumer thread — connects, declares queue,
        and starts consuming only when listening is enabled by the user."""

        logger.info(f"RabbitMQ consumer started on queue '{RABBITMQ_QUEUE}' (listening: OFF)")
        self._running = True
        while self._running:
            try:
                self._connection = self._connect()
                self._channel = self._connection.channel()
                self._channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
                self._channel.basic_qos(prefetch_count=1)

                if self._listening_enabled:
                    logger.info("Starting consumption (listening=ON)")
                    self._channel.basic_consume(queue=RABBITMQ_QUEUE, on_message_callback=self._on_message)
                    self._channel.start_consuming()
                else:
                    # Poll loop: wait for start() signal while keeping connection alive
                    while self._running and not self._listening_enabled:
                        try:
                            self._connection.sleep(1.0)
                        except Exception:
                            break  # connection died, exit inner loop to reconnect

                    if self._running and self._listening_enabled:
                        self._channel.basic_consume(queue=RABBITMQ_QUEUE, on_message_callback=self._on_message)
                        self._channel.start_consuming()

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
                self._channel = None
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
