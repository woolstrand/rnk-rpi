"""Tests for the /rnk/audio HTTP API."""

import io

from app import create_app
from app.audio import constants
from tests.conftest import FakeMotorDriver


def test_play_reads_upload_and_calls_player(client, fake_audio_player):
    resp = client.post(
        "/rnk/audio/play",
        data={"audio": (io.BytesIO(b"fake-wav-bytes"), "sound.wav")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "playing", "bytes": len(b"fake-wav-bytes")}
    assert fake_audio_player.calls == [b"fake-wav-bytes"]


def test_play_missing_file_field_returns_400(client):
    resp = client.post("/rnk/audio/play", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_play_empty_file_returns_400(client):
    resp = client.post(
        "/rnk/audio/play",
        data={"audio": (io.BytesIO(b""), "sound.wav")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_play_oversized_file_returns_413(client, monkeypatch):
    monkeypatch.setattr(constants, "MAX_AUDIO_BYTES", 4)
    resp = client.post(
        "/rnk/audio/play",
        data={"audio": (io.BytesIO(b"too-large"), "sound.wav")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 413
    assert "error" in resp.get_json()


def test_play_propagates_playback_errors(client, monkeypatch):
    from app.audio.player import PlaybackError

    def boom(data):
        raise PlaybackError("aplay is not installed")

    client.application.extensions["audio_player"] = boom
    resp = client.post(
        "/rnk/audio/play",
        data={"audio": (io.BytesIO(b"data"), "sound.wav")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 502
    assert resp.get_json() == {"error": "aplay is not installed"}


def test_play_returns_503_when_unconfigured():
    # audio_player defaults to the real ffmpeg/aplay pipeline unless
    # explicitly overridden; pass None to simulate "not configured".
    app = create_app(driver=FakeMotorDriver(), audio_player=None)
    app.extensions["audio_player"] = None
    app.extensions["scheduler"].start()
    try:
        app.config["TESTING"] = True
        client = app.test_client()
        resp = client.post(
            "/rnk/audio/play",
            data={"audio": (io.BytesIO(b"data"), "sound.wav")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 503
    finally:
        app.extensions["scheduler"].shutdown()
