"""Camera control API: ONVIF PTZ + RTSP snapshot proxy.

Endpoints (mounted at ``/rnk/camera``):

  POST /rnk/camera/ptz/absolute  move to an absolute pan/tilt/zoom position
  POST /rnk/camera/ptz/relative  move by a pan/tilt/zoom delta
  POST /rnk/camera/ptz/stop      stop any in-progress PTZ move
  POST /rnk/camera/home          reset to the camera's home/center position
  GET  /rnk/camera/status        current PTZ position + capabilities
  GET  /rnk/camera/snapshot      capture a single JPEG frame from the stream

All endpoints return 503 if no camera is configured (see ``.env.example``).
"""

import logging
import math

from flask import Blueprint, Response, current_app, jsonify, request

from ..camera import constants
from ..camera.ptz import PTZError
from ..camera.snapshot import SnapshotError

log = logging.getLogger(__name__)

camera_bp = Blueprint("camera", __name__, url_prefix="/rnk/camera")


def _ptz():
    return current_app.extensions.get("ptz_controller")


def _snapshot():
    return current_app.extensions.get("snapshot_source")


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _parse_axis(payload, key, low, high, required):
    if key not in payload:
        if required:
            raise ValueError(f"'{key}' is required")
        return None
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{key}' must be a number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"'{key}' must be a finite number")
    if not (low <= value <= high):
        raise ValueError(f"'{key}' must be between {low} and {high}")
    return value


def _parse_ptz_payload(payload, low, high):
    """Validate a PTZ request body and return (pan, tilt, zoom)."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    pan = _parse_axis(payload, "pan", low, high, required=True)
    tilt = _parse_axis(payload, "tilt", low, high, required=True)
    zoom = _parse_axis(
        payload, "zoom", constants.ZOOM_MIN, constants.ZOOM_MAX, required=False
    )
    return pan, tilt, zoom


@camera_bp.post("/ptz/absolute")
def ptz_absolute():
    """Move to an absolute pan/tilt (and optional zoom) position.

    Body: ``{"pan": -1..1, "tilt": -1..1, "zoom": 0..1 (optional)}``
    (ONVIF's normalized generic PTZ space; 0/0 is center).
    """
    controller = _ptz()
    if controller is None:
        return _error("camera is not configured", 503)

    payload = request.get_json(silent=True)
    if payload is None:
        return _error("request body must be valid JSON", 400)
    try:
        pan, tilt, zoom = _parse_ptz_payload(
            payload, constants.PAN_MIN, constants.PAN_MAX
        )
    except ValueError as exc:
        return _error(str(exc), 400)

    try:
        controller.absolute_move(pan, tilt, zoom)
    except PTZError as exc:
        return _error(str(exc), 501)
    except Exception:
        log.exception("absolute PTZ move failed")
        return _error("camera communication failed", 502)

    return jsonify({"status": "ok", "pan": pan, "tilt": tilt, "zoom": zoom}), 200


@camera_bp.post("/ptz/relative")
def ptz_relative():
    """Move by a pan/tilt (and optional zoom) delta from the current position.

    Body: ``{"pan": -1..1, "tilt": -1..1, "zoom": -1..1 (optional)}``.
    """
    controller = _ptz()
    if controller is None:
        return _error("camera is not configured", 503)

    payload = request.get_json(silent=True)
    if payload is None:
        return _error("request body must be valid JSON", 400)
    try:
        pan, tilt, zoom = _parse_ptz_payload(
            payload, constants.RELATIVE_MIN, constants.RELATIVE_MAX
        )
    except ValueError as exc:
        return _error(str(exc), 400)

    try:
        controller.relative_move(pan, tilt, zoom)
    except PTZError as exc:
        return _error(str(exc), 501)
    except Exception:
        log.exception("relative PTZ move failed")
        return _error("camera communication failed", 502)

    return jsonify({"status": "ok", "pan": pan, "tilt": tilt, "zoom": zoom}), 200


@camera_bp.post("/ptz/stop")
def ptz_stop():
    """Stop any pan/tilt/zoom movement currently in progress."""
    controller = _ptz()
    if controller is None:
        return _error("camera is not configured", 503)
    try:
        controller.stop()
    except Exception:
        log.exception("PTZ stop failed")
        return _error("camera communication failed", 502)
    return jsonify({"status": "stopped"})


@camera_bp.post("/home")
def home():
    """Reset pan/tilt to the camera's home/central position."""
    controller = _ptz()
    if controller is None:
        return _error("camera is not configured", 503)
    try:
        controller.home()
    except PTZError as exc:
        return _error(str(exc), 501)
    except Exception:
        log.exception("PTZ home failed")
        return _error("camera communication failed", 502)
    return jsonify({"status": "ok"})


@camera_bp.get("/status")
def status():
    """Current PTZ position/capabilities, as reported by the camera."""
    controller = _ptz()
    if controller is None:
        return _error("camera is not configured", 503)
    try:
        position = controller.status()
        capabilities = controller.capabilities()
    except Exception:
        log.exception("PTZ status query failed")
        return _error("camera communication failed", 502)
    return jsonify({**position, "capabilities": capabilities})


@camera_bp.get("/snapshot")
def snapshot():
    """Capture and return a single JPEG frame from the RTSP stream.

    Query param ``scaled=true`` downsizes the frame to 640x480; omit (or
    ``scaled=false``) for the stream's native resolution.
    """
    capture = _snapshot()
    if capture is None:
        return _error("camera is not configured", 503)

    scaled = request.args.get("scaled", "false").strip().lower() in (
        "1", "true", "yes",
    )
    try:
        jpeg_bytes = capture(scaled)
    except SnapshotError as exc:
        return _error(str(exc), 502)

    return Response(jpeg_bytes, mimetype="image/jpeg")
