import queue
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(f"backend.{__name__}")

class Dispatcher:
    def __init__(
        self,
        in_queue: queue.Queue,
        service_provider,
        sse_queue_put: callable,
        max_workers: int = 4,
    ):
        self._in_queue = in_queue
        self._service_provider = service_provider
        self._sse_queue_put_callback = sse_queue_put

        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="dispatcher",
        )

        self._sem = threading.Semaphore(max_workers)
        self._stop = threading.Event()

    # -------------------------
    # lifecycle
    # -------------------------
    def stop(self):
        self._stop.set()

    def run(self):
        logger.info("dispatcher started")
        while not self._stop.is_set():
            try:
                item = self._in_queue.get(timeout=1)
            except queue.Empty:
                continue

            # backpressure
            self._sem.acquire()

            try:
                future = self._executor.submit(self._service_provider.run, item)
                future.add_done_callback(self._done_callback)
            except Exception:
                # submit failed → rollback resources
                self._sem.release()
                self._in_queue.task_done()
                logger.exception("submit failed")
                continue

    # -------------------------
    # worker callback
    # -------------------------
    def _done_callback(self, future):
        try:
            payloads = future.result()
            for payload_type, payload in payloads:
                logger.debug(f"Dispatching result payload: {payload_type}")
                self._sse_queue_put_callback(payload_type, payload)

        except Exception:
            logger.exception("worker failed")

            self._in_queue.task_done()
            self._sem.release()
            return

        self._in_queue.task_done()
        self._sem.release()

    # -------------------------
    # cleanup
    # -------------------------
    def shutdown(self, wait=True):
        self.stop()
        self._executor.shutdown(wait=wait)