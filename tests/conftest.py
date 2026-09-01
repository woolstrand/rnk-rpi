"""Shared test fixtures.

The fake driver implements the same interface as ``app.motor.driver.MotorDriver``
but records calls instead of touching GPIO, so the whole app (scheduler + API)
can be exercised on machines without a Raspberry Pi.
"""

import threading

import pytest

from app import create_app
from app.scheduler import CommandScheduler


class FakeMotorDriver:
    """Records motion calls; never touches hardware."""

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def _record(self, name, *args):
        with self._lock:
            self.calls.append((name, args))

    def setup(self):
        self._record("setup")

    def cleanup(self):
        self._record("cleanup")

    def forward(self, speed=0.5):
        self._record("forward", speed)

    def backward(self, speed=0.5):
        self._record("backward", speed)

    def left(self, speed=0.5):
        self._record("left", speed)

    def right(self, speed=0.5):
        self._record("right", speed)

    def stop(self):
        self._record("stop")

    def motion_calls(self):
        """All calls except setup/cleanup/stop, in order."""
        with self._lock:
            return [c for c in self.calls if c[0] not in ("setup", "cleanup", "stop")]


@pytest.fixture
def fake_driver():
    return FakeMotorDriver()


@pytest.fixture
def app(fake_driver):
    """Flask app wired to a fake driver and a started scheduler."""
    import app.motor.constants as constants

    constants.STOP_CHECK_INTERVAL_S = 0.001

    application = create_app(driver=fake_driver)
    application.config["TESTING"] = True
    application.extensions["scheduler"].start()
    yield application
    application.extensions["scheduler"].shutdown()


@pytest.fixture
def client(app):
    return app.test_client()
