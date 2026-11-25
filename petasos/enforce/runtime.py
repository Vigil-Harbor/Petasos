"""The two event loops an enforcer owns.

Evaluation and tool-result scans run on separate loops so a slow result scan
cannot hold up the next tool call. Pipeline access is serialised by the
inspect lock. ``close`` stops both loops and is safe to call twice.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import threading
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Coroutine

_T = TypeVar("_T")


class AsyncBridge:
    """Background loops for one enforcer. Not shared with another enforcer."""

    def __init__(self) -> None:
        self.inspect = threading.Lock()
        self._eval_loop: asyncio.AbstractEventLoop | None = None
        self._eval_thread: threading.Thread | None = None
        self._eval_ready = threading.Event()
        self._ingest_loop: asyncio.AbstractEventLoop | None = None
        self._ingest_thread: threading.Thread | None = None
        self._ingest_ready = threading.Event()
        self._ingest_lock: asyncio.Lock | None = None
        self._closed = False
        self._lock = threading.Lock()
        self._pending: set[concurrent.futures.Future[Any]] = set()

    def run(self, coro: Coroutine[Any, Any, _T], timeout: float) -> _T:
        """Run ``coro`` on the evaluation loop and cancel it if ``timeout`` elapses.

        A timeout raises ``concurrent.futures.TimeoutError``.
        """
        try:
            loop = self._ensure_eval()
        except Exception:
            coro.close()
            raise
        return self._submit(coro, loop, timeout)

    def run_ingest(self, coro: Coroutine[Any, Any, _T], timeout: float) -> _T:
        """Run a result scan with a caller-side deadline, even if its loop stops."""
        try:
            loop = self._ensure_ingest()
        except Exception:
            coro.close()
            raise
        return self._submit(coro, loop, timeout)

    def _submit(
        self, coro: Coroutine[Any, Any, _T], loop: asyncio.AbstractEventLoop, timeout: float
    ) -> _T:
        # Submission and close are ordered: shutdown cannot miss a future that
        # has been handed to its loop but has not yet started running there.
        with self._lock:
            if self._closed or loop.is_closed():
                coro.close()
                raise RuntimeError("enforcer is closed")
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            self._pending.add(future)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise
        finally:
            with self._lock:
                self._pending.discard(future)

    def close(self) -> None:
        """Stop both loops. A second call does nothing."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pending = tuple(self._pending)
            pairs = (
                (self._eval_loop, self._eval_thread),
                (self._ingest_loop, self._ingest_thread),
            )
        for future in pending:
            future.cancel()
        for loop, thread in pairs:
            if loop is not None and not loop.is_closed():
                # Queue the stop even before run_forever starts. The loop may
                # also finish between the closed check and this submission.
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(loop.stop)
            if (
                thread is not None
                and thread.is_alive()
                and thread is not threading.current_thread()
            ):
                thread.join(timeout=1.0)

    def _ensure_eval(self) -> asyncio.AbstractEventLoop:
        return self._ensure(
            "eval",
            self._eval_ready,
            "_eval_thread",
            "_eval_loop",
            "petasos-async",
            ingest=False,
        )

    def _ensure_ingest(self) -> asyncio.AbstractEventLoop:
        return self._ensure(
            "ingest",
            self._ingest_ready,
            "_ingest_thread",
            "_ingest_loop",
            "petasos-ingest",
            ingest=True,
        )

    def _ensure(
        self,
        label: str,
        ready: threading.Event,
        thread_attr: str,
        loop_attr: str,
        thread_name: str,
        *,
        ingest: bool,
    ) -> asyncio.AbstractEventLoop:
        """Start the named loop once. Other callers wait for the same start."""
        with self._lock:
            if self._closed:
                raise RuntimeError("enforcer is closed")
            thread = getattr(self, thread_attr)
            if thread is None or not thread.is_alive():
                ready.clear()
                setattr(self, loop_attr, None)

                def _target() -> None:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    with self._lock:
                        if self._closed:
                            loop.close()
                            ready.set()
                            return
                        if ingest:
                            self._ingest_lock = asyncio.Lock()
                        setattr(self, loop_attr, loop)
                        ready.set()
                    try:
                        loop.run_forever()
                    finally:
                        tasks = asyncio.all_tasks(loop)
                        for task in tasks:
                            task.cancel()
                        if tasks:
                            loop.run_until_complete(asyncio.wait(tasks, timeout=0.5))
                        loop.close()

                started = threading.Thread(target=_target, name=thread_name, daemon=True)
                setattr(self, thread_attr, started)
                started.start()
        if not ready.wait(5):
            raise RuntimeError(f"{label} loop did not start")
        loop = getattr(self, loop_attr)
        if not isinstance(loop, asyncio.AbstractEventLoop):
            raise RuntimeError(f"{label} loop did not start")
        return loop

    @property
    def ingest_lock(self) -> asyncio.Lock | None:
        """The lock the result scan holds while it inspects. ``None`` before the loop starts."""
        return self._ingest_lock
