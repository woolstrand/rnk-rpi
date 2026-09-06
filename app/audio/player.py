"""Immediate audio playback via ffmpeg (decode) piped into aplay (ALSA).

ffmpeg decodes whatever format is given (wav, mp3, ogg, ...) to raw PCM,
which is piped straight into aplay so playback uses the system's default
ALSA output device. ffmpeg is already a project dependency (see
``app/camera/snapshot.py``); aplay ships in the ``alsa-utils`` package
(installed via apt; see ``scripts/setup.sh``).
"""

import logging
import subprocess
import threading

from . import constants

log = logging.getLogger(__name__)


class PlaybackError(RuntimeError):
    """Raised when playback can't even be started (e.g. missing binaries)."""


def play_file(data: bytes) -> None:
    """Decode ``data`` (raw bytes of an audio file) and play it immediately.

    Starting playback is fire-and-forget: decoding/playing happens on a
    background thread so the caller (an HTTP request handler) isn't held
    open for the audio's duration. Only failures to *launch* the pipeline
    raise; failures during decode/playback itself are logged.

    Raises:
        PlaybackError: ``data`` is empty, or ffmpeg/aplay isn't installed.
    """
    if not data:
        raise PlaybackError("audio data is empty")

    try:
        decode = subprocess.Popen(
            [
                "ffmpeg", "-loglevel", "error",
                "-i", "pipe:0",
                "-f", "s16le",
                "-ar", str(constants.SAMPLE_RATE),
                "-ac", str(constants.CHANNELS),
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise PlaybackError("ffmpeg is not installed") from exc

    try:
        play = subprocess.Popen(
            [
                "aplay", "-q",
                "-f", "S16_LE",
                "-r", str(constants.SAMPLE_RATE),
                "-c", str(constants.CHANNELS),
            ],
            stdin=decode.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        decode.kill()
        decode.stdout.close()
        raise PlaybackError("aplay is not installed") from exc

    decode.stdout.close()  # let `play` see EOF/SIGPIPE once decode exits

    threading.Thread(
        target=_feed_and_wait, args=(decode, play, data), daemon=True
    ).start()


def _feed_and_wait(decode, play, data: bytes) -> None:
    try:
        decode.stdin.write(data)
    except BrokenPipeError:
        pass
    finally:
        decode.stdin.close()

    decode.wait()
    play.wait()

    if decode.returncode != 0:
        stderr = decode.stderr.read() if decode.stderr else b""
        log.error(
            "ffmpeg failed to decode audio (exit %s): %s",
            decode.returncode,
            stderr.decode("utf-8", "replace").strip(),
        )
    if play.returncode != 0:
        stderr = play.stderr.read() if play.stderr else b""
        log.error(
            "aplay failed to play audio (exit %s): %s",
            play.returncode,
            stderr.decode("utf-8", "replace").strip(),
        )
