"""Public API for the rnk-rpi platform.

Endpoints (mounted at ``/rnk``):

  POST /rnk/schedule  enqueue a motion command
  GET  /rnk/schedule  inspect the queue
  POST /rnk/stop      halt the motors and clear the queue
"""

import math

from flask import Blueprint, current_app, jsonify, request

from ..motor import constants

rnk_bp = Blueprint("rnk", __name__, url_prefix="/rnk")


def _scheduler():
    return current_app.extensions["scheduler"]


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _parse_command(payload):
    """Validate a request payload and return (kind, value) or raise ValueError."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    if "move" in payload and "rotate" in payload:
        raise ValueError("provide exactly one of 'move' or 'rotate'")

    if "move" in payload:
        kind, limit = "move", constants.MAX_MOVE_CM
        unit = "cm"
    elif "rotate" in payload:
        kind, limit = "rotate", constants.MAX_ROTATE_DEG
        unit = "deg"
    else:
        raise ValueError("payload must contain 'move' (cm) or 'rotate' (deg)")

    value = payload[kind]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{kind}' must be a number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"'{kind}' must be a finite number")
    if value == 0:
        raise ValueError(f"'{kind}' must not be zero")
    if abs(value) > limit:
        raise ValueError(f"'{kind}' must not exceed {limit} {unit} in magnitude")

    return kind, value


@rnk_bp.post("/schedule")
def schedule():
    """Enqueue a motion command.

    Accepts ``{"move": <cm>}`` or ``{"rotate": <deg>}``. Positive values
    move forward / rotate clockwise; negative values move backward /
    rotate counter-clockwise. Commands execute strictly one by one, in
    the order received.
    """
    payload = request.get_json(silent=True)
    if payload is None:
        return _error("request body must be valid JSON", 400)

    try:
        kind, value = _parse_command(payload)
    except ValueError as exc:
        return _error(str(exc), 400)

    scheduler = _scheduler()
    try:
        position = scheduler.enqueue(kind, value)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        return _error("command queue is full", 503)

    return (
        jsonify(
            {
                "status": "queued",
                "command": {"kind": kind, "value": value},
                "position": position,
                "queue_size": scheduler.queue_size,
            }
        ),
        202,
    )


@rnk_bp.get("/schedule")
def get_schedule():
    """Return the current queue: the running command (if any) and pending ones."""
    scheduler = _scheduler()
    return jsonify(
        {
            "busy": scheduler.is_busy,
            "queue_size": scheduler.queue_size,
            "queue": scheduler.pending(),
        }
    )


@rnk_bp.post("/stop")
def stop():
    """Halt the current command immediately and clear the pending queue."""
    scheduler = _scheduler()
    cleared = scheduler.stop()
    return jsonify({"status": "stopped", "cleared": cleared})
