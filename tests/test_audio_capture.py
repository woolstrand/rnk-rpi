"""Tests for continuous audio capture + streaming (app/audio/source.py, stream_server.py)."""

import socket
import subprocess
import threading
import time

import pytest

from app.audio.source import AudioSourceError, CameraAudioSource, probe_camera_audio
from app.audio.stream_server import AudioStreamServer


# -- probe_camera_audio -----------------------------------------------------


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_probe_raises_when_ffprobe_missing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(AudioSourceError, match="ffprobe"):
        probe_camera_audio("rtsp://fake")


def test_probe_raises_on_timeout(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=5)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(AudioSourceError, match="timed out"):
        probe_camera_audio("rtsp://fake")


def test_probe_raises_when_no_audio_stream(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompletedProcess(returncode=0, stdout=b"")
    )
    with pytest.raises(AudioSourceError, match="no audio track"):
        probe_camera_audio("rtsp://fake")


def test_probe_raises_when_ffprobe_fails(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _FakeCompletedProcess(returncode=1, stderr=b"connection refused"),
    )
    with pytest.raises(AudioSourceError, match="could not probe"):
        probe_camera_audio("rtsp://fake")


def test_probe_succeeds_when_audio_stream_present(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompletedProcess(returncode=0, stdout=b"audio\n")
    )
    probe_camera_audio("rtsp://fake")  # does not raise


# -- CameraAudioSource -------------------------------------------------------


class _FakePopen:
    """Fakes just enough of subprocess.Popen for CameraAudioSource.frames()."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.stdout = _FakeStdout(self._chunks)
        self.stderr = _FakeStdout([])
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class _FakeStdout:
    def __init__(self, chunks):
        self._chunks = chunks
        self._closed = False

    def read(self, n):
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def close(self):
        self._closed = True


def test_camera_audio_source_yields_chunks_and_stops_on_eof(monkeypatch):
    fake_proc = _FakePopen([b"\x00\x01" * 10, b"\x02\x03" * 10])
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: fake_proc)

    source = CameraAudioSource("rtsp://fake")
    chunks = list(source.frames())

    assert chunks == [b"\x00\x01" * 10, b"\x02\x03" * 10]
    assert fake_proc.returncode == -15  # terminated by close()


def test_camera_audio_source_raises_when_ffmpeg_missing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "Popen", boom)
    source = CameraAudioSource("rtsp://fake")
    with pytest.raises(AudioSourceError, match="ffmpeg"):
        list(source.frames())


# -- AudioStreamServer --------------------------------------------------------


class _FakeSource:
    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    def frames(self):
        yield from self._chunks

    def close(self):
        self.closed = True


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_stream_server_sends_captured_frames_to_client():
    port = _free_port()
    fake_source = _FakeSource([b"abcd", b"efgh"])
    server = AudioStreamServer(
        source_factory=lambda: fake_source, host="127.0.0.1", port=port
    )
    server.start()
    try:
        deadline = time.monotonic() + 2
        received = b""
        with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
            sock.settimeout(0.5)
            while len(received) < 8 and time.monotonic() < deadline:
                try:
                    chunk = sock.recv(64)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                received += chunk
        assert received == b"abcdefgh"
    finally:
        server.shutdown()


def test_stream_server_disabled_when_prestart_check_fails():
    port = _free_port()

    def failing_check():
        raise AudioSourceError("no audio track")

    server = AudioStreamServer(
        source_factory=lambda: _FakeSource([]),
        prestart_check=failing_check,
        host="127.0.0.1",
        port=port,
    )
    server.start()
    time.sleep(0.2)
    with pytest.raises(OSError):
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            pass
    server.shutdown()
