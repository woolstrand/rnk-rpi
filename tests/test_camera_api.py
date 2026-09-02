"""Tests for the /rnk/camera HTTP API."""

import pytest

from app import create_app
from tests.conftest import FakeMotorDriver


def test_ptz_absolute_moves_and_echoes_position(client, fake_ptz):
    resp = client.post(
        "/rnk/camera/ptz/absolute", json={"pan": 0.5, "tilt": -0.25, "zoom": 0.1}
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "pan": 0.5, "tilt": -0.25, "zoom": 0.1}
    assert fake_ptz.calls == [("absolute_move", 0.5, -0.25, 0.1)]


def test_ptz_absolute_without_zoom(client, fake_ptz):
    resp = client.post("/rnk/camera/ptz/absolute", json={"pan": 0.0, "tilt": 0.0})
    assert resp.status_code == 200
    assert fake_ptz.calls == [("absolute_move", 0.0, 0.0, None)]


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing pan/tilt
        {"pan": 0.5},  # missing tilt
        {"pan": "left", "tilt": 0},  # non-numeric
        {"pan": float("nan"), "tilt": 0},
        {"pan": 2.0, "tilt": 0},  # out of range
        {"pan": 0, "tilt": 0, "zoom": 5.0},  # zoom out of range
    ],
)
def test_ptz_absolute_invalid_payload_returns_400(client, payload):
    resp = client.post("/rnk/camera/ptz/absolute", json=payload)
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_ptz_relative_moves(client, fake_ptz):
    resp = client.post(
        "/rnk/camera/ptz/relative", json={"pan": -0.1, "tilt": 0.2}
    )
    assert resp.status_code == 200
    assert fake_ptz.calls == [("relative_move", -0.1, 0.2, None)]


def test_ptz_stop(client, fake_ptz):
    resp = client.post("/rnk/camera/ptz/stop")
    assert resp.status_code == 200
    assert fake_ptz.calls == [("stop",)]


def test_home_resets_position(client, fake_ptz):
    fake_ptz.absolute_move(0.8, 0.8)
    resp = client.post("/rnk/camera/home")
    assert resp.status_code == 200
    assert fake_ptz.calls[-1] == ("home",)
    assert fake_ptz.status()["pan"] == 0.0
    assert fake_ptz.status()["tilt"] == 0.0


def test_status_reports_position_and_capabilities(client, fake_ptz):
    fake_ptz.absolute_move(0.3, -0.4, 0.6)
    resp = client.get("/rnk/camera/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["pan"] == 0.3
    assert data["tilt"] == -0.4
    assert data["zoom"] == 0.6
    assert data["capabilities"] == {"absolute": True, "relative": True, "home": True}


def test_snapshot_returns_jpeg(client, fake_snapshot):
    resp = client.get("/rnk/camera/snapshot")
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    assert resp.data == b"\xff\xd8\xff\xd9"
    assert fake_snapshot.calls == [False]


def test_snapshot_scaled_true_is_passed_through(client, fake_snapshot):
    resp = client.get("/rnk/camera/snapshot?scaled=true")
    assert resp.status_code == 200
    assert fake_snapshot.calls == [True]


def test_camera_endpoints_return_503_when_unconfigured():
    # No ptz_controller/snapshot_source given, and no .env in the test
    # environment, so create_app() leaves the camera extensions unset.
    app = create_app(driver=FakeMotorDriver())
    app.extensions["scheduler"].start()
    try:
        app.config["TESTING"] = True
        client = app.test_client()
        assert client.get("/rnk/camera/status").status_code == 503
        assert client.get("/rnk/camera/snapshot").status_code == 503
        assert client.post("/rnk/camera/home").status_code == 503
        assert (
            client.post("/rnk/camera/ptz/absolute", json={"pan": 0, "tilt": 0}).status_code
            == 503
        )
    finally:
        app.extensions["scheduler"].shutdown()
