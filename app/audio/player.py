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
import time

from . import constants

log = logging.getLogger(__name__)

# aplay occasionally fails to open the ALSA device on the first try (seen in
# the wild as "audio open error: Unknown error 524"), which looks transient -
# a retry a moment later succeeds. Give it a few tries before giving up.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_S = 0.5


class PlaybackError(RuntimeError):
    """Raised when playback can't even be started (e.g. missing binaries)."""


def play_file(data: bytes, volume: float = constants.DEFAULT_VOLUME) -> None:
    """Decode ``data`` (raw bytes of an audio file) and play it immediately.

    Starting playback is fire-and-forget: decoding/playing happens on a
    background thread so the caller (an HTTP request handler) isn't held
    open for the audio's duration. Only failures to *launch* the pipeline
    raise; failures during decode/playback itself are logged (after being
    retried a few times, since they're often a transient ALSA hiccup).

    ``volume`` is a gain multiplier applied while decoding (1.0 = unchanged).

    Raises:
        PlaybackError: ``data`` is empty, or ffmpeg/aplay isn't installed.
    """
    if not data:
        raise PlaybackError("audio data is empty")

    decode, play = _spawn_pipeline(volume)

    threading.Thread(
        target=_feed_and_wait_with_retry, args=(decode, play, data, volume), daemon=True
    ).start()


def _spawn_pipeline(volume: float) -> tuple[subprocess.Popen, subprocess.Popen]:
    """Start the ffmpeg decode -> aplay pipeline. Neither process is fed yet."""
    try:
        decode = subprocess.Popen(
            [
                "ffmpeg", "-loglevel", "error",
                "-i", "pipe:0",
                "-filter:a", f"volume={volume}",
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
    return decode, play


def _feed_and_wait_with_retry(
    decode: subprocess.Popen, play: subprocess.Popen, data: bytes, volume: float, attempt: int = 1
) -> None:
    if _feed_and_wait(decode, play, data) or attempt >= RETRY_ATTEMPTS:
        return
    log.warning("retrying audio playback (attempt %s/%s)", attempt + 1, RETRY_ATTEMPTS)
    time.sleep(RETRY_BACKOFF_S)
    try:
        decode, play = _spawn_pipeline(volume)
    except PlaybackError as exc:
        log.error("could not retry audio playback: %s", exc)
        return
    _feed_and_wait_with_retry(decode, play, data, volume, attempt + 1)


def _feed_and_wait(decode: subprocess.Popen, play: subprocess.Popen, data: bytes) -> bool:
    """Feed ``data`` through the pipeline and wait for it to finish. Returns success."""
    try:
        decode.stdin.write(data)
    except BrokenPipeError:
        pass
    finally:
        decode.stdin.close()

    decode.wait()
    play.wait()

    ok = True
    if decode.returncode != 0:
        ok = False
        stderr = decode.stderr.read() if decode.stderr else b""
        log.error(
            "ffmpeg failed to decode audio (exit %s): %s",
            decode.returncode,
            stderr.decode("utf-8", "replace").strip(),
        )
    if play.returncode != 0:
        ok = False
        stderr = play.stderr.read() if play.stderr else b""
        log.error(
            "aplay failed to play audio (exit %s): %s",
            play.returncode,
            stderr.decode("utf-8", "replace").strip(),
        )
    return ok
