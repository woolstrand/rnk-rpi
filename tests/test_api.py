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
    assert data["command"] == {"kind": "move", "value": 70.0}
    assert data["position"] == 1
    assert data["queue_size"] >= 1


def test_post_rotate_returns_202(client):
    resp = client.post("/rnk/schedule", json={"rotate": 35})
    assert resp.status_code == 202
    assert resp.get_json()["command"] == {"kind": "rotate", "value": 35.0}


@pytest.mark.parametrize(
    "payload",
    [
        {"move": 70, "rotate": 35},  # both
        {},  # neither
        {"move": 0},
        {"move": -5},
        {"move": "ten"},
        {"move": None},
        {"move": float("inf")},
        {"move": float("nan")},
        {"move": 10**9},  # over MAX_MOVE_CM
        {"rotate": 0},
        {"rotate": -35},
        {"rotate": 10**9},  # over MAX_ROTATE_DEG
        {"forward": 10},  # unknown key
    ],
)
def test_post_invalid_payload_returns_400(client, payload):
    resp = client.post("/rnk/schedule", json=payload)
    assert resp.status_code == 400
    assert "error" in resp.get_json()


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


def test_queue_full_returns_503(client, app):
    scheduler = app.extensions["scheduler"]
    # Fill the queue directly (bypassing the API) up to the limit.
    for _ in range(scheduler._max_queue_size):
        scheduler.enqueue("move", 1.0)

    resp = client.post("/rnk/schedule", json={"move": 1})
    assert resp.status_code == 503
    assert "full" in resp.get_json()["error"]

    scheduler.stop()
