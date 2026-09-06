"""Tests for the /rnk HTTP API."""

import time

import pytest


def test_post_move_returns_202(client):
    resp = client.post(
        "/rnk/schedule", json={"move": 70}
    )
    assert resp.status_code == 202
    data = resp.get_json()
    assert data["status"] == "queued"
    assert data["command"] == {"kind": "move", "value": 70.0, "speed": pytest.approx(0.4)}
    assert data["position"] == 1
    assert data["queue_size"] >= 1


def test_post_rotate_returns_202(client):
    resp = client.post("/rnk/schedule", json={"rotate": 35})
    assert resp.status_code == 202
    assert resp.get_json()["command"] == {
        "kind": "rotate",
        "value": 35.0,
        "speed": pytest.approx(0.4),
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"move": 70, "rotate": 35},  # both
        {},  # neither
        {"move": 0},
        {"move": "ten"},
        {"move": None},
        {"move": float("inf")},
        {"move": float("nan")},
        {"move": 10**9},  # over MAX_MOVE_CM
        {"move": -(10**9)},  # over MAX_MOVE_CM in magnitude
        {"rotate": 0},
        {"rotate": 10**9},  # over MAX_ROTATE_DEG
        {"rotate": -(10**9)},  # over MAX_ROTATE_DEG in magnitude
        {"forward": 10},  # unknown key
        {"move": 10, "speed": 0},  # speed out of range
        {"move": 10, "speed": 1.5},  # speed out of range
        {"move": 10, "speed": "fast"},  # speed not a number
    ],
)
def test_post_invalid_payload_returns_400(client, payload):
    resp = client.post("/rnk/schedule", json=payload)
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_post_move_accepts_custom_speed(client):
    resp = client.post("/rnk/schedule", json={"move": 70, "speed": 1.0})
    assert resp.status_code == 202
    assert resp.get_json()["command"] == {"kind": "move", "value": 70.0, "speed": 1.0}


def test_post_negative_move_returns_202(client):
    resp = client.post("/rnk/schedule", json={"move": -70})
    assert resp.status_code == 202
    assert resp.get_json()["command"] == {
        "kind": "move",
        "value": -70.0,
        "speed": pytest.approx(0.4),
    }


def test_post_negative_rotate_returns_202(client):
    resp = client.post("/rnk/schedule", json={"rotate": -35})
    assert resp.status_code == 202
    assert resp.get_json()["command"] == {
        "kind": "rotate",
        "value": -35.0,
        "speed": pytest.approx(0.4),
    }


def test_post_non_json_body_returns_400(client):
    resp = client.post("/rnk/schedule", data="move=70", content_type="text/plain")
    assert resp.status_code == 400


def test_get_schedule_reflects_queue(client):
    client.post("/rnk/schedule", json={"move": 1})
    client.post("/rnk/schedule", json={"rotate": 10})
    time.sleep(0.05)

    resp = client.get("/rnk/schedule")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["queue_size"] >= 1
    assert all(item["state"] in ("running", "queued") for item in data["queue"])


def test_get_schedule_empty(client):
    resp = client.get("/rnk/schedule")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["queue"] == []
    assert data["queue_size"] == 0
    assert data["busy"] is False
    assert data["error"] is None


def test_stop_clears_queue(client):
    client.post("/rnk/schedule", json={"move": 30})
    client.post("/rnk/schedule", json={"move": 1})
    time.sleep(0.05)

    resp = client.post("/rnk/stop")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "stopped"
    assert data["cleared"] >= 1

    # After stopping, the queue is empty and the robot is idle.
    time.sleep(0.05)
    data = client.get("/rnk/schedule").get_json()
    assert data["queue"] == []
    assert data["busy"] is False


def test_stop_does_not_block_later_commands(client):
    """Regression test: stop() must not prevent later commands from running."""
    client.post("/rnk/schedule", json={"move": 30})
    time.sleep(0.05)
    client.post("/rnk/stop")

    resp = client.post("/rnk/schedule", json={"move": 1})
    assert resp.status_code == 202

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not client.get("/rnk/schedule").get_json()["busy"]:
            break
        time.sleep(0.01)
    assert not client.get("/rnk/schedule").get_json()["busy"]


def test_errors_reset_endpoint_clears_error(client, app):
    scheduler = app.extensions["scheduler"]
    scheduler._error = {"message": "simulated stall", "at": time.time()}

    data = client.get("/rnk/schedule").get_json()
    assert data["error"]["message"] == "simulated stall"

    # Queuing new commands is refused while an error is active.
    resp = client.post("/rnk/schedule", json={"move": 1})
    assert resp.status_code == 409

    resp = client.post("/rnk/errors/reset")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"

    data = client.get("/rnk/schedule").get_json()
    assert data["error"] is None

    resp = client.post("/rnk/schedule", json={"move": 1})
    assert resp.status_code == 202


def test_queue_full_returns_503(client, app):
    scheduler = app.extensions["scheduler"]
    # Fill the queue directly (bypassing the API) up to the limit.
    for _ in range(scheduler._max_queue_size):
        scheduler.enqueue("move", 1.0)

    resp = client.post("/rnk/schedule", json={"move": 1})
    assert resp.status_code == 503
    assert "full" in resp.get_json()["error"]

    scheduler.stop()
