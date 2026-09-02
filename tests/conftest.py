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


class FakePTZController:
    """Records PTZ calls and fakes a position; never touches a real camera."""

    def __init__(self, capabilities=None):
        self.calls = []
        self._capabilities = capabilities or {
            "absolute": True,
            "relative": True,
            "home": True,
        }
        self._position = {"pan": 0.0, "tilt": 0.0, "zoom": 0.0}

    def capabilities(self):
        return dict(self._capabilities)

    def absolute_move(self, pan, tilt, zoom=None):
        self.calls.append(("absolute_move", pan, tilt, zoom))
        self._position = {
            "pan": pan,
            "tilt": tilt,
            "zoom": zoom if zoom is not None else self._position["zoom"],
        }

    def relative_move(self, pan, tilt, zoom=None):
        self.calls.append(("relative_move", pan, tilt, zoom))

    def stop(self):
        self.calls.append(("stop",))

    def home(self):
        self.calls.append(("home",))
        self._position = {"pan": 0.0, "tilt": 0.0, "zoom": self._position["zoom"]}

    def status(self):
        return {**self._position, "moving": False}


#: Minimal valid JPEG (SOI + EOI markers), enough to exercise the snapshot API.
FAKE_JPEG_BYTES = b"\xff\xd8\xff\xd9"


@pytest.fixture
def fake_driver():
    return FakeMotorDriver()


@pytest.fixture
def fake_ptz():
    return FakePTZController()


@pytest.fixture
def fake_snapshot():
    calls = []

    def capture(scaled):
        calls.append(scaled)
        return FAKE_JPEG_BYTES

    capture.calls = calls
    return capture


@pytest.fixture
def app(fake_driver, fake_ptz, fake_snapshot):
    """Flask app wired to a fake driver/camera and a started scheduler."""
    import app.motor.constants as constants

    constants.STOP_CHECK_INTERVAL_S = 0.001

    application = create_app(
        driver=fake_driver, ptz_controller=fake_ptz, snapshot_source=fake_snapshot
    )
    application.config["TESTING"] = True
    application.extensions["scheduler"].start()
    yield application
    application.extensions["scheduler"].shutdown()


@pytest.fixture
def client(app):
    return app.test_client()
