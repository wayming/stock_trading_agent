"""Unit tests for Dispatcher — queue-driven worker orchestrator."""

import queue
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from unittest import mock
from unittest.mock import MagicMock, patch, call

import pytest

from dispatcher import Dispatcher


#
# Fixtures (dependency injection)
#


@pytest.fixture
def in_queue():
    """Real queue.Queue — lightweight, no network, safe under test."""
    return queue.Queue()


@pytest.fixture
def service_provider():
    """Fake ServiceProvider whose .run() returns a canned payload list."""
    svc = MagicMock()
    svc.run.return_value = [
        ("signal", {"id": "s1", "sentiment": "neutral"}),
        ("news", {"id": "n1", "content": "test"}),
        ("analysis", {"id": "a1", "reasoning": "ok"}),
    ]
    return svc


@pytest.fixture
def sse_queue_put():
    """Spy callback — records every (event_type, payload) pushed."""
    return MagicMock()


@pytest.fixture
def dispatcher(in_queue, service_provider, sse_queue_put):
    """Dispatcher wired with all three injected deps."""
    return Dispatcher(
        in_queue=in_queue,
        service_provider=service_provider,
        sse_queue_put=sse_queue_put,
        max_workers=2,
    )


#
# stop
#


class TestStop:
    def test_sets_stop_event(self, dispatcher):
        dispatcher.stop()
        assert dispatcher._stop.is_set()


#
# run — lifecycle & edge-cases
#


class TestRunLifecycle:
    def test_breaks_when_stop_set_before_run(self, dispatcher):
        """If _stop is already set, run() returns immediately."""
        dispatcher._stop.set()
        dispatcher.run()  # must not block
        # reaching here is success

    def test_continues_on_queue_empty(self, dispatcher):
        """queue.Empty is swallowed; loop continues until stopped."""
        with patch.object(dispatcher._in_queue, "get", side_effect=queue.Empty):
            # Run in a thread and stop after a short sleep
            t = threading.Thread(target=dispatcher.run, daemon=True)
            t.start()
            time.sleep(0.15)
            dispatcher.stop()
            t.join(timeout=2)
            assert not t.is_alive()


#
# run — item processing
#


class TestRunProcessing:
    def test_submits_to_executor_and_calls_service_provider(
        self, dispatcher, in_queue, service_provider
    ):
        """A valid item on the queue is submitted to the executor."""
        body = b'{"content": "breaking news"}'
        in_queue.put(body)

        # Stop after processing the single item
        original_submit = dispatcher._executor.submit

        def _submit(fn, *args, **kwargs):
            result = original_submit(fn, *args, **kwargs)
            dispatcher.stop()  # stop after first submission
            return result

        with patch.object(dispatcher._executor, "submit", side_effect=_submit):
            dispatcher.run()

        service_provider.run.assert_called_once_with(body)

    def test_acquires_semaphore_before_submit(self, dispatcher, in_queue):
        """Backpressure: semaphore is acquired before each submit."""
        in_queue.put(b"item1")

        with patch.object(dispatcher._sem, "acquire", wraps=dispatcher._sem.acquire) as spy_acquire:
            original_submit = dispatcher._executor.submit

            def _submit(fn, *args, **kwargs):
                dispatcher.stop()
                return original_submit(fn, *args, **kwargs)

            with patch.object(dispatcher._executor, "submit", side_effect=_submit):
                dispatcher.run()

        spy_acquire.assert_called_once()

    def test_rolls_back_semaphore_on_submit_failure(self, dispatcher, in_queue):
        """If executor.submit raises, release the semaphore + task_done."""
        body = b"item"
        in_queue.put(body)

        with patch.object(dispatcher._executor, "submit", side_effect=RuntimeError("boom")):
            original_get = dispatcher._in_queue.get

            # We need to avoid an infinite loop, so stop after the failure iteration
            call_count = [0]

            def _side_effect_get(timeout=1):
                call_count[0] += 1
                if call_count[0] == 2:
                    dispatcher.stop()
                print(f"get called {call_count[0]} times, timeout={timeout}")
                return original_get(1)

            with patch.object(dispatcher._in_queue, "get", side_effect=_side_effect_get):
                dispatcher.run()

        # Semaphore should be released (back to initial value)
        assert dispatcher._sem._value == 2  # max_workers=2, all released


#
# _done_callback
#


class TestDoneCallback:
    def test_calls_sse_queue_put_for_every_payload(
        self, dispatcher, sse_queue_put, in_queue
    ):
        """Each (type, payload) from the future result is forwarded to sse_queue_put."""
        future = Future()
        future.set_result([
            ("signal", {"a": 1}),
            ("news", {"b": 2}),
            ("analysis", {"c": 3}),
        ])

        dispatcher._done_callback(future)

        assert sse_queue_put.call_count == 3
        sse_queue_put.assert_has_calls([
            call("signal", {"a": 1}),
            call("news", {"b": 2}),
            call("analysis", {"c": 3}),
        ])

    def test_calls_task_done_and_releases_semaphore(self, dispatcher):
        """On success, task_done() and sem.release() are both called."""
        future = Future()
        future.set_result([])

        with (
            patch.object(dispatcher._in_queue, "task_done") as mock_task_done,
            patch.object(dispatcher._sem, "release") as mock_release,
        ):
            dispatcher._done_callback(future)

        mock_task_done.assert_called_once()
        mock_release.assert_called_once()

    def test_handles_exception_in_future_result(self, dispatcher):
        """If the future raised an exception, log it and still clean up."""
        future = Future()
        future.set_exception(ValueError("worker exploded"))

        with (
            patch.object(dispatcher._in_queue, "task_done") as mock_task_done,
            patch.object(dispatcher._sem, "release") as mock_release,
            patch("dispatcher.logger") as mock_logger,
        ):
            dispatcher._done_callback(future)

        mock_logger.exception.assert_called_once_with("worker failed")
        mock_task_done.assert_called_once()
        mock_release.assert_called_once()

    def test_handles_exception_during_sse_callback(self, dispatcher, sse_queue_put):
        """If sse_queue_put raises, still release resources."""
        sse_queue_put.side_effect = RuntimeError("sse dead")

        future = Future()
        future.set_result([("signal", {"x": 1})])

        with (
            patch.object(dispatcher._in_queue, "task_done") as mock_task_done,
            patch.object(dispatcher._sem, "release") as mock_release,
            patch("dispatcher.logger") as mock_logger,
        ):
            dispatcher._done_callback(future)

        mock_logger.exception.assert_called_once_with("worker failed")
        mock_task_done.assert_called_once()
        mock_release.assert_called_once()

    def test_empty_payload_list_does_not_call_sse(self, dispatcher, sse_queue_put):
        """Zero-length payload list -> no sse calls, still cleans up."""
        future = Future()
        future.set_result([])

        with (
            patch.object(dispatcher._in_queue, "task_done") as mock_task_done,
            patch.object(dispatcher._sem, "release") as mock_release,
        ):
            dispatcher._done_callback(future)

        sse_queue_put.assert_not_called()
        mock_task_done.assert_called_once()
        mock_release.assert_called_once()


#
# shutdown
#


class TestShutdown:
    def test_calls_stop_and_executor_shutdown(self, dispatcher):
        with (
            patch.object(dispatcher, "stop") as mock_stop,
            patch.object(dispatcher._executor, "shutdown") as mock_shutdown,
        ):
            dispatcher.shutdown(wait=True)

        mock_stop.assert_called_once()
        mock_shutdown.assert_called_once_with(wait=True)

    def test_shutdown_defaults_to_wait_true(self, dispatcher):
        with patch.object(dispatcher._executor, "shutdown") as mock_shutdown:
            dispatcher.shutdown()
        mock_shutdown.assert_called_once_with(wait=True)

    def test_shutdown_wait_false(self, dispatcher):
        with patch.object(dispatcher._executor, "shutdown") as mock_shutdown:
            dispatcher.shutdown(wait=False)
        mock_shutdown.assert_called_once_with(wait=False)


#
# Integration (no mocks on collaborator internals)
#


class TestIntegration:
    def test_end_to_end_single_item(self, in_queue, sse_queue_put):
        """End-to-end: Dispatcher pulls a real item and pushes results through."""
        svc = MagicMock()
        svc.run.return_value = [
            ("signal", {"sentiment": "bullish"}),
            ("news", {"content": "hello"}),
        ]

        d = Dispatcher(
            in_queue=in_queue,
            service_provider=svc,
            sse_queue_put=sse_queue_put,
            max_workers=1,
        )

        in_queue.put(b'{"content": "test news", "symbol": "AAPL"}')

        # Run in thread, wait for completion, then stop
        t = threading.Thread(target=d.run, daemon=True)
        t.start()

        # Wait for the item to be consumed (max 3 s)
        deadline = time.time() + 3
        while not in_queue.empty() and time.time() < deadline:
            time.sleep(0.05)

        # Give the callback a moment to fire
        time.sleep(0.2)

        d.shutdown(wait=True)
        t.join(timeout=2)

        svc.run.assert_called_once()
        assert sse_queue_put.call_count >= 2

    def test_multiple_items_are_all_processed(self, in_queue, sse_queue_put):
        """N items on the queue -> N calls to service_provider.run."""
        svc = MagicMock()
        svc.run.return_value = []

        d = Dispatcher(
            in_queue=in_queue,
            service_provider=svc,
            sse_queue_put=sse_queue_put,
            max_workers=2,
        )

        for i in range(5):
            in_queue.put(f'{{"i": {i}}}'.encode())

        t = threading.Thread(target=d.run, daemon=True)
        t.start()

        # Wait until all items processed
        deadline = time.time() + 5
        while svc.run.call_count < 5 and time.time() < deadline:
            time.sleep(0.1)

        d.shutdown(wait=True)
        t.join(timeout=2)

        assert svc.run.call_count == 5
