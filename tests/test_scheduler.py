"""Tests for the command scheduler (queue, ordering, stop, shutdown)."""

import time

import pytest

from app import constants
from app.scheduler import CommandScheduler
from tests.conftest import FakeMotorDriver


@pytest.fixture(autouse=True)
def fast_stop_ticks():
    original = constants.STOP_CHECK_INTERVAL_S
    constants.STOP_CHECK_INTERVAL_S = 0.001
    yield
    constants.STOP_CHECK_INTERVAL_S = original


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
        scheduler.enqueue("move", -5)
    with pytest.raises(ValueError):
        scheduler.enqueue("move", constants.MAX_MOVE_CM + 1)
    with pytest.raises(ValueError):
        scheduler.enqueue("rotate", 0)
    with pytest.raises(ValueError):
        scheduler.enqueue("rotate", constants.MAX_ROTATE_DEG + 1)
    with pytest.raises(ValueError):
        scheduler.enqueue("teleport", 1)
    assert scheduler.queue_size == 0


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
