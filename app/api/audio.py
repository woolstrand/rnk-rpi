"""Audio playback API: upload a file and play it on the default output.

Endpoints (mounted at ``/rnk/audio``):

  POST /rnk/audio/play  upload an audio file and play it immediately
"""

import logging

from flask import Blueprint, current_app, jsonify, request

from ..audio import constants
from ..audio.player import PlaybackError

log = logging.getLogger(__name__)

audio_bp = Blueprint("audio", __name__, url_prefix="/rnk/audio")


def _player():
    return current_app.extensions.get("audio_player")


def _error(message: str, status: int):
    return jsonify({"error": message}), status


@audio_bp.post("/play")
def play():
    """Play an uploaded audio file immediately on the default audio output.

    Body: ``multipart/form-data`` with a single file field named ``audio``
    (any format ffmpeg can decode: wav, mp3, ogg, ...). Playback starts in
    the background; the response does not wait for it to finish.
    """
    player = _player()
    if player is None:
        return _error("audio playback is not configured", 503)

    upload = request.files.get("audio")
    if upload is None:
        return _error("request must include an 'audio' file field", 400)

    data = upload.read(constants.MAX_AUDIO_BYTES + 1)
    if not data:
        return _error("uploaded audio file is empty", 400)
    if len(data) > constants.MAX_AUDIO_BYTES:
        return _error(
            f"audio file exceeds the {constants.MAX_AUDIO_BYTES} byte limit", 413
        )

    try:
        player(data)
    except PlaybackError as exc:
        return _error(str(exc), 502)
    except Exception:
        log.exception("audio playback failed")
        return _error("audio playback failed", 502)

    return jsonify({"status": "playing", "bytes": len(data)}), 200
