"""Audio source abstraction for continuous capture + streaming.

The Pi has no microphone of its own yet, so the only implementation today
extracts the audio track from the ONVIF camera's RTSP stream via ffmpeg
(the same tool already used for JPEG snapshots, see ``camera/snapshot.py``).

Everything downstream (``stream_server.AudioStreamServer``) only depends on
the ``AudioSource`` interface, so a different source (e.g. a USB
microphone) can be swapped in later without touching the streaming code.
"""

from __future__ import annotations

import abc
import logging
import subprocess
from typing import Iterator

from . import capture_constants as constants

log = logging.getLogger(__name__)


class AudioSourceError(RuntimeError):
    """Raised when an audio source cannot be started (e.g. no audio track)."""


class AudioSource(abc.ABC):
    """A continuous source of raw PCM audio (16 kHz mono 16-bit signed LE)."""

    @abc.abstractmethod
    def frames(self) -> Iterator[bytes]:
        """Yield raw PCM chunks until the source ends or :meth:`close` is called."""

    @abc.abstractmethod
    def close(self) -> None:
        """Release any underlying resources (subprocess, handles, ...). Idempotent."""


def probe_camera_audio(rtsp_url: str, timeout_s: float = constants.PROBE_TIMEOUT_S) -> None:
    """Check that ``rtsp_url`` actually has an audio track before we rely on it.

    Raises:
        AudioSourceError: ffprobe is missing, the probe times out (camera
            unreachable), or the stream has no audio track (no built-in
            microphone, or audio disabled in its RTSP profile). The
            underlying ffprobe stderr (which may echo the RTSP URL/
            credentials) is logged, never included in the raised message.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-rtsp_transport", "tcp",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        rtsp_url,
    ]
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_s
        )
    except FileNotFoundError as exc:
        raise AudioSourceError("ffprobe is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioSourceError(
            f"timed out probing the camera stream for audio ({timeout_s}s) - "
            "camera may be unreachable"
        ) from exc

    if result.returncode != 0:
        log.error(
            "ffprobe failed to probe the camera stream (exit %s): %s",
            result.returncode,
            result.stderr.decode("utf-8", "replace").strip(),
        )
        raise AudioSourceError("could not probe the camera stream for audio")

    if b"audio" not in result.stdout:
        raise AudioSourceError(
            "camera RTSP stream has no audio track (no built-in microphone, "
            "or audio is disabled in its stream profile)"
        )

    log.info("camera RTSP stream has an audio track; audio capture enabled")


class CameraAudioSource(AudioSource):
    """Extracts the audio track from the camera's RTSP stream via ffmpeg."""

    def __init__(
        self,
        rtsp_url: str,
        sample_rate: int = constants.SAMPLE_RATE,
        channels: int = constants.CHANNELS,
    ):
        self._rtsp_url = rtsp_url
        self._sample_rate = sample_rate
        self._channels = channels
        self._proc: subprocess.Popen | None = None

    def frames(self) -> Iterator[bytes]:
        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-rtsp_transport", "tcp",
            "-i", self._rtsp_url,
            "-vn", "-map", "0:a:0",
            "-ac", str(self._channels),
            "-ar", str(self._sample_rate),
            "-f", "s16le",
            "pipe:1",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except FileNotFoundError as exc:
            raise AudioSourceError("ffmpeg is not installed") from exc

        first_chunk = True
        try:
            while True:
                chunk = self._proc.stdout.read(constants.FRAME_BYTES)
                if not chunk:
                    break
                if first_chunk:
                    log.info("receiving audio from the camera stream (ffmpeg is decoding it)")
                    first_chunk = False
                yield chunk
        finally:
            self._terminate()

    def close(self) -> None:
        self._terminate()

    def _terminate(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        if proc.returncode not in (None, 0, -15):  # -15 = terminated by us (SIGTERM)
            stderr = proc.stderr.read() if proc.stderr else b""
            log.error(
                "ffmpeg audio capture exited unexpectedly (code %s): %s",
                proc.returncode,
                stderr.decode("utf-8", "replace").strip(),
            )
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
