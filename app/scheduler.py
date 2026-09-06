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
        speed: PWM duty cycle (0.0, 1.0] to drive the motors at.
        added_at: Unix timestamp when the command was enqueued.
    """

    kind: str
    value: float
    speed: float = constants.DEFAULT_SPEED
    added_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "value": self.value,
            "speed": self.speed,
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

    def enqueue(
        self, kind: str, value: float, speed: float = constants.DEFAULT_SPEED
    ) -> int:
        """Add a command to the queue.

        Returns:
            The 1-based position of the command in the queue.

        Raises:
            ValueError: if ``kind`` is not "move"/"rotate", the value is
                zero or exceeds the configured limits in magnitude, or
                ``speed`` is not within (0, 1].
            queue.Full: if the queue already holds MAX_QUEUE_SIZE commands.
        """
        if kind == "move":
            if value == 0 or abs(value) > constants.MAX_MOVE_CM:
                raise ValueError(
                    f"move value must be nonzero and within \u00b1{constants.MAX_MOVE_CM} cm, got {value}"
                )
        elif kind == "rotate":
            if value == 0 or abs(value) > constants.MAX_ROTATE_DEG:
                raise ValueError(
                    f"rotate value must be nonzero and within \u00b1{constants.MAX_ROTATE_DEG} deg, got {value}"
                )
        else:
            raise ValueError(f"unknown command kind: {kind!r}")

        if not (0 < speed <= 1):
            raise ValueError(f"speed must be within (0, 1], got {speed}")

        self._queue.put_nowait(
            Command(kind=kind, value=float(value), speed=float(speed))
        )
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
            target_ticks = kinematics.move_ticks(cmd.value)
            if cmd.value >= 0:
                self._driver.forward(cmd.speed)
            else:
                self._driver.backward(cmd.speed)
        else:  # rotate
            target_ticks = kinematics.rotate_ticks(cmd.value)
            if cmd.value >= 0:
                self._driver.left(cmd.speed)
            else:
                self._driver.right(cmd.speed)

        log.info(
            "executing %s %s at speed %.2f for %d encoder ticks",
            cmd.kind, cmd.value, cmd.speed, target_ticks,
        )
        self._driver.reset_ticks()
        while True:
            if self._stop_event.is_set():
                log.info("stop requested during %s", cmd.kind)
                return
            ticks = self._driver.get_ticks()
            if min(ticks.values()) >= target_ticks:
                return
            time.sleep(constants.STOP_CHECK_INTERVAL_S)
