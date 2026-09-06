"""Tests for the command scheduler (queue, ordering, stop, shutdown)."""

import time

import pytest

import app.scheduler as scheduler_module
from app.motor import constants
from app.scheduler import CommandScheduler
from tests.conftest import FakeMotorDriver


@pytest.fixture(autouse=True)
def fast_stop_ticks():
    original_interval = constants.STOP_CHECK_INTERVAL_S
    original_timeout = constants.STALL_TIMEOUT_S
    constants.STOP_CHECK_INTERVAL_S = 0.001
    constants.STALL_TIMEOUT_S = 0.02
    yield
    constants.STOP_CHECK_INTERVAL_S = original_interval
    constants.STALL_TIMEOUT_S = original_timeout


class ScriptedTicksDriver:
    """Driver whose get_ticks() replays a scripted sequence (repeating the
    last entry once exhausted), for deterministic compensation/stall tests."""

    def __init__(self, tick_sequence):
        self.calls = []
        self._remaining = list(tick_sequence)
        self._last_ticks = {"left": 0, "right": 0}

    def setup(self):
        self.calls.append(("setup", ()))

    def cleanup(self):
        self.calls.append(("cleanup", ()))

    def forward(self, speed=0.4):
        self.calls.append(("forward", (speed,)))

    def backward(self, speed=0.4):
        self.calls.append(("backward", (speed,)))

    def left(self, speed=0.4):
        self.calls.append(("left", (speed,)))

    def right(self, speed=0.4):
        self.calls.append(("right", (speed,)))

    def stop(self):
        self.calls.append(("stop", ()))

    def drive(self, left_direction, left_speed, right_direction, right_speed):
        self.calls.append(
            ("drive", (left_direction, left_speed, right_direction, right_speed))
        )

    def reset_ticks(self):
        pass

    def get_ticks(self):
        if self._remaining:
            self._last_ticks = self._remaining.pop(0)
        return dict(self._last_ticks)


@pytest.fixture
def driver():
    return FakeMotorDriver()


@pytest.fixture
def scheduler(driver):
    sched = CommandScheduler(driver)
    sched.start()
    yield sched
    sched.shutdown()


def test_commands_execute_one_by_one_in_order(driver, scheduler):
    scheduler.enqueue("move", 1.0)
    scheduler.enqueue("rotate", 1.0)
    scheduler.enqueue("move", 2.0)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        calls = driver.motion_calls()
        if len(calls) >= 3:
            break
        time.sleep(0.01)

    names = [name for name, _ in driver.motion_calls()]
    assert names[:3] == ["forward", "left", "forward"]
    # After the last command the driver must be stopped.
    assert driver.calls[-1][0] == "stop"


def test_negative_move_drives_backward(driver, scheduler):
    scheduler.enqueue("move", -1.0)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if driver.motion_calls():
            break
        time.sleep(0.01)

    names = [name for name, _ in driver.motion_calls()]
    assert names[:1] == ["backward"]


def test_negative_rotate_drives_right(driver, scheduler):
    scheduler.enqueue("rotate", -1.0)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if driver.motion_calls():
            break
        time.sleep(0.01)

    names = [name for name, _ in driver.motion_calls()]
    assert names[:1] == ["right"]


def test_stop_halts_current_command_and_clears_queue(driver, scheduler):
    # A 30 cm move takes a while at the placeholder speed; stop mid-flight.
    scheduler.enqueue("move", 30.0)
    time.sleep(0.05)  # let the worker pick it up
    assert scheduler.is_busy

    cleared = scheduler.stop()
    assert cleared == 0  # nothing else was queued

    # The worker must stop the driver shortly after the stop request.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if driver.calls[-1][0] == "stop":
            break
        time.sleep(0.01)
    assert driver.calls[-1][0] == "stop"
    assert not scheduler.is_busy


def test_stop_clears_pending_commands(driver, scheduler):
    scheduler.enqueue("move", 30.0)
    scheduler.enqueue("move", 1.0)
    scheduler.enqueue("rotate", 1.0)
    time.sleep(0.05)

    cleared = scheduler.stop()
    assert cleared == 2  # the two commands still in the queue
    assert scheduler.queue_size == 0
    assert scheduler.pending() == []


def test_pending_reflects_queue(driver, scheduler):
    scheduler.enqueue("move", 5.0)
    scheduler.enqueue("rotate", 45.0)
    time.sleep(0.05)

    pending = scheduler.pending()
    assert len(pending) >= 1
    assert all(item["state"] in ("running", "queued") for item in pending)
    kinds = [item["kind"] for item in pending]
    assert "move" in kinds


def test_enqueue_rejects_invalid_values(driver, scheduler):
    with pytest.raises(ValueError):
        scheduler.enqueue("move", 0)
    with pytest.raises(ValueError):
        scheduler.enqueue("move", constants.MAX_MOVE_CM + 1)
    with pytest.raises(ValueError):
        scheduler.enqueue("move", -(constants.MAX_MOVE_CM + 1))
    with pytest.raises(ValueError):
        scheduler.enqueue("rotate", 0)
    with pytest.raises(ValueError):
        scheduler.enqueue("rotate", constants.MAX_ROTATE_DEG + 1)
    with pytest.raises(ValueError):
        scheduler.enqueue("teleport", 1)
    with pytest.raises(ValueError):
        scheduler.enqueue("move", 1.0, speed=0)
    with pytest.raises(ValueError):
        scheduler.enqueue("move", 1.0, speed=1.5)
    assert scheduler.queue_size == 0


def test_enqueue_accepts_negative_values(driver, scheduler):
    assert scheduler.enqueue("move", -5) == 1
    assert scheduler.enqueue("rotate", -10) == 2


def test_enqueue_returns_position(driver, scheduler):
    assert scheduler.enqueue("move", 1.0) == 1
    assert scheduler.enqueue("rotate", 10.0) == 2
    assert scheduler.enqueue("move", 2.0) == 3


def test_shutdown_stops_driver(driver, scheduler):
    scheduler.shutdown()
    assert driver.calls[-1][0] == "stop"
    assert "cleanup" in [name for name, _ in driver.calls]
    # Idempotent:
    scheduler.shutdown()


def test_stop_does_not_prevent_later_commands(driver, scheduler):
    """Regression test: stop() must not kill the worker thread."""
    scheduler.enqueue("move", 1.0)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not driver.motion_calls():
        time.sleep(0.01)
    scheduler.stop()

    # The worker thread must still be running and able to execute a
    # command enqueued after the stop.
    scheduler.enqueue("move", 1.0)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if len(driver.motion_calls()) >= 2:
            break
        time.sleep(0.01)

    names = [name for name, _ in driver.motion_calls()]
    assert names.count("forward") >= 2


def test_power_balancing_compensates_diverging_wheels(monkeypatch):
    monkeypatch.setattr(scheduler_module.kinematics, "move_ticks", lambda v: 10)
    driver = ScriptedTicksDriver(
        [
            {"left": 0, "right": 0},
            {"left": 5, "right": 0},
            {"left": 8, "right": 3},
            {"left": 10, "right": 10},
        ]
    )
    sched = CommandScheduler(driver)
    sched.start()
    try:
        sched.enqueue("move", 10.0)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and sched.is_busy:
            time.sleep(0.01)
        assert sched.error is None
        drive_calls = [args for name, args in driver.calls if name == "drive"]
        assert drive_calls, "expected compensation to adjust per-wheel duty"
        left_dir, left_speed, right_dir, right_speed = drive_calls[0]
        assert left_dir == 1 and right_dir == 1
        assert left_speed < 0.4 < right_speed  # left was ahead, so it's slowed
    finally:
        sched.shutdown()


def test_stall_from_sustained_divergence_records_error(monkeypatch):
    monkeypatch.setattr(scheduler_module.kinematics, "move_ticks", lambda v: 10_000)
    driver = ScriptedTicksDriver([{"left": 50, "right": 0}])
    sched = CommandScheduler(driver)
    sched.start()
    try:
        sched.enqueue("move", 10.0)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and sched.error is None:
            time.sleep(0.01)
        assert sched.error is not None
        assert "diverged" in sched.error["message"]
        assert not sched.is_busy
        assert driver.calls[-1][0] == "stop"

        with pytest.raises(RuntimeError):
            sched.enqueue("move", 1.0)

        sched.reset_errors()
        assert sched.error is None
        assert sched.enqueue("move", 1.0) == 1
    finally:
        sched.shutdown()


def test_stall_from_no_progress_records_error(monkeypatch):
    monkeypatch.setattr(scheduler_module.kinematics, "move_ticks", lambda v: 10_000)
    driver = ScriptedTicksDriver([{"left": 0, "right": 0}])
    sched = CommandScheduler(driver)
    sched.start()
    try:
        sched.enqueue("move", 10.0)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and sched.error is None:
            time.sleep(0.01)
        assert sched.error is not None
        assert "no encoder progress" in sched.error["message"]
    finally:
        sched.shutdown()
