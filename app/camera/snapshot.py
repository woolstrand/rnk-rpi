"""Single-frame JPEG capture from the camera's RTSP stream, via ffmpeg.

ffmpeg is invoked as a subprocess (rather than an OpenCV/numpy binding) so
this module has no heavy imaging dependency — just the ``ffmpeg`` binary,
which must be installed on the Pi (``apt-get install ffmpeg``; handled by
``scripts/setup.sh``).
"""

import logging
import subprocess

from . import constants

log = logging.getLogger(__name__)


class SnapshotError(RuntimeError):
    """Raised when a frame could not be captured from the RTSP stream."""


def capture_frame(
    rtsp_url: str,
    scaled: bool = False,
    timeout_s: float = constants.SNAPSHOT_TIMEOUT_S,
) -> bytes:
    """Grab a single JPEG frame from ``rtsp_url``.

    Args:
        scaled: if True, downscale to SCALED_WIDTH x SCALED_HEIGHT; otherwise
            return the frame at the stream's native resolution.

    Returns:
        Raw JPEG bytes.

    Raises:
        SnapshotError: ffmpeg is missing, times out, or fails to produce a
            frame. The underlying ffmpeg output (which may echo the RTSP
            URL/credentials on connection failures) is logged, never
            included in the raised message, so it can't leak into an HTTP
            response.
    """
    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-frames:v", "1",
    ]
    if scaled:
        cmd += ["-vf", f"scale={constants.SCALED_WIDTH}:{constants.SCALED_HEIGHT}"]
    cmd += ["-f", "image2", "-vcodec", "mjpeg", "pipe:1"]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SnapshotError("ffmpeg is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise SnapshotError(
            f"timed out waiting for a frame ({timeout_s}s)"
        ) from exc

    if result.returncode != 0 or not result.stdout:
        log.error(
            "ffmpeg failed to capture a frame (exit %s): %s",
            result.returncode,
            result.stderr.decode("utf-8", "replace").strip(),
        )
        raise SnapshotError("ffmpeg failed to capture a frame from the camera stream")

    return result.stdout
