"""SSE manager for broadcasting real-time events to connected frontend clients."""

import asyncio
import json


class SSEManager:
    """Manages SSE subscriptions and broadcasts events to all connected clients."""

    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    async def subscribe(self) -> asyncio.Queue:
        """Register a new client. Returns an asyncio.Queue for the client to read from."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._queues.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        """Remove a client queue."""
        if queue in self._queues:
            self._queues.remove(queue)

    async def broadcast(self, event_type: str, data: dict):
        """Push an SSE event to all connected clients."""
        # Format as SSE: event line + data line(s) + blank line
        payload = json.dumps(data, ensure_ascii=False)
        message = f"event: {event_type}\ndata: {payload}\n\n"
        dead: list[asyncio.Queue] = []
        for queue in self._queues:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                dead.append(queue)
        for q in dead:
            self.unsubscribe(q)

    @property
    def client_count(self) -> int:
        return len(self._queues)
