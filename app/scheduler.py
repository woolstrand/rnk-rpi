"""Command scheduler: executes queued motion commands strictly one by one.

A single daemon worker thread pulls commands off a thread-safe queue and
executes each one to completion before starting the next. This guarantees
that the platform never receives conflicting motor commands.

Safety:
  * After every command (and on every stop/shutdown) the driver is
    explicitly stopped, so the motors are never left energized.
  * :meth:`stop` interrupts the currently running command within at most
    ``STOP_CHECK_INTERVAL_S`` seconds and clears the pending queue, but
    the worker thread itself keeps running so subsequent commands still
    execute normally.
  * While a command runs, cumulative encoder ticks from the two wheels
    are compared; a small divergence is compensated by nudging each
    wheel's PWM duty, while a divergence (or a total lack of progress)
    that persists beyond ``STALL_TIMEOUT_S`` is treated as a stall or
    obstacle: the motors are stopped, the queue is cleared, and the
    failure is recorded until :meth:`reset_errors` is called.
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
        # Interrupts only the command currently executing (set by stop()).
        self._interrupt_event = threading.Event()
        # Ends the worker thread itself (set only by shutdown()). Keeping
        # this separate from _interrupt_event means stop() no longer kills
        # the worker thread, so commands enqueued after a stop still run.
        self._shutdown_event = threading.Event()
        self._lock = threading.Lock()
        self._error_lock = threading.Lock()
        self._error: Optional[dict] = None
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
            self._shutdown_event.clear()
            self._interrupt_event.clear()
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

        if self.error is not None:
            raise RuntimeError(
                "a motion error is active; call the errors-reset endpoint "
                "before queuing new commands"
            )

        self._queue.put_nowait(
            Command(kind=kind, value=float(value), speed=float(speed))
        )
        return self._queue.qsize()

    def stop(self) -> int:
        """Halt the current command and clear the pending queue.

        Returns:
            Number of pending commands that were discarded.
        """
        self._interrupt_event.set()
        cleared = self._drain_queue()
        log.info("stop requested; cleared %d pending command(s)", cleared)
        return cleared

    @property
    def error(self) -> Optional[dict]:
        """The last recorded stall/obstacle error, or None if healthy."""
        with self._error_lock:
            return dict(self._error) if self._error else None

    def reset_errors(self) -> None:
        """Clear a recorded motion error, re-enabling new commands."""
        with self._error_lock:
            self._error = None
        log.info("motion errors reset")

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
        self._shutdown_event.set()
        with self._lock:
            worker, self._worker = self._worker, None
        if worker is not None and worker.is_alive():
            worker.join(timeout=5)
        self._driver.cleanup()

    # ------------------------------------------------------------------
    # Worker internals
    # ------------------------------------------------------------------

    def _drain_queue(self) -> int:
        """Discard all pending commands. Returns the number discarded."""
        cleared = 0
        while True:
            try:
                self._queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        return cleared

    def _abort_with_error(self, message: str) -> None:
        """Stop the motors, discard the queue, and record a motion error."""
        self._driver.stop()
        self._drain_queue()
        with self._error_lock:
            self._error = {"message": message, "at": time.time()}
        log.error("motion error: %s", message)

    def _run(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                cmd = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if cmd is None:  # poison pill
                break
            self._interrupt_event.clear()
            if self.error is not None:
                log.warning("dropping %r: unresolved motion error", cmd)
                self._queue.task_done()
                continue
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
            left_dir = right_dir = 1 if cmd.value >= 0 else -1
            if cmd.value >= 0:
                self._driver.forward(cmd.speed)
            else:
                self._driver.backward(cmd.speed)
        else:  # rotate
            target_ticks = kinematics.rotate_ticks(cmd.value)
            left_dir = 1 if cmd.value >= 0 else -1
            right_dir = -left_dir
            if cmd.value >= 0:
                self._driver.left(cmd.speed)
            else:
                self._driver.right(cmd.speed)

        log.info(
            "executing %s %s at speed %.2f for %d encoder ticks",
            cmd.kind, cmd.value, cmd.speed, target_ticks,
        )
        self._driver.reset_ticks()

        diverged_since: Optional[float] = None
        last_progress = 0
        last_progress_time = time.monotonic()

        while True:
            if self._interrupt_event.is_set():
                log.info("stop requested during %s", cmd.kind)
                return

            ticks = self._driver.get_ticks()
            left_ticks, right_ticks = ticks["left"], ticks["right"]
            progress = min(left_ticks, right_ticks)
            if progress >= target_ticks:
                return

            now = time.monotonic()
            diff = left_ticks - right_ticks

            # --- power-balancing compensation ---
            # If one wheel is pulling ahead of the other, nudge its duty
            # down and the lagging wheel's duty up to straighten out.
            if abs(diff) > constants.TICK_BALANCE_THRESHOLD:
                correction = min(
                    abs(diff) * constants.TICK_BALANCE_GAIN,
                    constants.MAX_SPEED_CORRECTION,
                )
                boosted = min(1.0, cmd.speed + correction)
                cut = max(0.0, cmd.speed - correction)
                if diff > 0:  # left wheel ahead of right
                    left_speed, right_speed = cut, boosted
                else:  # right wheel ahead of left
                    left_speed, right_speed = boosted, cut
                self._driver.drive(left_dir, left_speed, right_dir, right_speed)

            # --- stall / obstacle detection ---
            # Divergence that compensation can't correct within a short
            # grace period, or a total lack of encoder progress, means a
            # wheel is physically blocked (obstacle, stall, etc.).
            if abs(diff) > constants.STALL_DIVERGENCE_TICKS:
                diverged_since = diverged_since or now
                if now - diverged_since > constants.STALL_TIMEOUT_S:
                    self._abort_with_error(
                        f"{cmd.kind} aborted: wheel encoders diverged by "
                        f"{diff} ticks (left={left_ticks}, right={right_ticks}) "
                        f"and compensation did not recover within "
                        f"{constants.STALL_TIMEOUT_S}s"
                    )
                    return
            else:
                diverged_since = None

            if progress > last_progress:
                last_progress = progress
                last_progress_time = now
            elif now - last_progress_time > constants.STALL_TIMEOUT_S:
                self._abort_with_error(
                    f"{cmd.kind} aborted: no encoder progress for "
                    f"{constants.STALL_TIMEOUT_S}s (left={left_ticks}, "
                    f"right={right_ticks}); possible stall or obstacle"
                )
                return

            time.sleep(constants.STOP_CHECK_INTERVAL_S)
