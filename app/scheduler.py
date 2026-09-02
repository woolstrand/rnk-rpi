"""Command scheduler: executes queued motion commands strictly one by one.

A single daemon worker thread pulls commands off a thread-safe queue and
executes each one to completion before starting the next. This guarantees
that the platform never receives conflicting motor commands.

Safety:
  * After every command (and on every stop/shutdown) the driver is
    explicitly stopped, so the motors are never left energized.
  * :meth:`stop` interrupts the currently running command within at most
    ``STOP_CHECK_INTERVAL_S`` seconds and clears the pending queue.
"""

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from .motor import constants
from .motor import kinematics

log = logging.getLogger(__name__)


@dataclass
class Command:
    """A single queued motion command.

    Attributes:
        kind: "move" (value in cm) or "rotate" (value in degrees).
        value: Magnitude of the command.
        added_at: Unix timestamp when the command was enqueued.
    """

    kind: str
    value: float
    added_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "value": self.value,
            "added_at": self.added_at,
        }


class CommandScheduler:
    """Thread-safe FIFO executor for motion commands."""

    def __init__(self, driver, max_queue_size: int = constants.MAX_QUEUE_SIZE):
        self._driver = driver
        self._max_queue_size = max_queue_size
        self._queue: "queue.Queue[Optional[Command]]" = queue.Queue()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._current: Optional[Command] = None
        self._driver.setup()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the worker thread. Idempotent."""
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop_event.clear()
            self._worker = threading.Thread(
                target=self._run, name="rnk-scheduler", daemon=True
            )
            self._worker.start()

    def enqueue(self, kind: str, value: float) -> int:
        """Add a command to the queue.

        Returns:
            The 1-based position of the command in the queue.

        Raises:
            ValueError: if ``kind`` is not "move"/"rotate" or the value
                is out of the configured limits.
            queue.Full: if the queue already holds MAX_QUEUE_SIZE commands.
        """
        if kind == "move":
            if not (0 < value <= constants.MAX_MOVE_CM):
                raise ValueError(
                    f"move value must be in (0, {constants.MAX_MOVE_CM}] cm, got {value}"
                )
        elif kind == "rotate":
            if not (0 < value <= constants.MAX_ROTATE_DEG):
                raise ValueError(
                    f"rotate value must be in (0, {constants.MAX_ROTATE_DEG}] deg, got {value}"
                )
        else:
            raise ValueError(f"unknown command kind: {kind!r}")

        self._queue.put_nowait(Command(kind=kind, value=float(value)))
        return self._queue.qsize()

    def stop(self) -> int:
        """Halt the current command and clear the pending queue.

        Returns:
            Number of pending commands that were discarded.
        """
        self._stop_event.set()
        cleared = 0
        while True:
            try:
                self._queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        log.info("stop requested; cleared %d pending command(s)", cleared)
        return cleared

    def pending(self) -> list:
        """Snapshot of the queue (oldest first) plus the running command."""
        items = []
        if self._current is not None:
            items.append({**self._current.to_dict(), "state": "running"})
        q = self._queue
        while True:
            try:
                cmd = q.get_nowait()
            except queue.Empty:
                break
            items.append({**cmd.to_dict(), "state": "queued"})
            q.put(cmd)
        return items

    @property
    def is_busy(self) -> bool:
        return self._current is not None or not self._queue.empty()

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def shutdown(self) -> None:
        """Stop everything and release the driver. Safe to call twice."""
        self.stop()
        with self._lock:
            worker, self._worker = self._worker, None
        if worker is not None and worker.is_alive():
            worker.join(timeout=5)
        self._driver.cleanup()

    # ------------------------------------------------------------------
    # Worker internals
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                cmd = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if cmd is None:  # poison pill
                break
            self._current = cmd
            try:
                self._execute(cmd)
            except Exception:
                log.exception("command %r failed", cmd)
            finally:
                self._driver.stop()
                self._current = None
                self._queue.task_done()

    def _execute(self, cmd: Command) -> None:
        if cmd.kind == "move":
            duration = kinematics.move_time_s(cmd.value)
            self._driver.forward()
        else:  # rotate
            duration = kinematics.rotate_time_s(cmd.value)
            self._driver.left()

        log.info(
            "executing %s %s for %.3fs", cmd.kind, cmd.value, duration
        )
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                log.info("stop requested during %s", cmd.kind)
                return
            time.sleep(
                min(constants.STOP_CHECK_INTERVAL_S, deadline - time.monotonic())
            )
