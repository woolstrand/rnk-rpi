"""Entry point for the rnk-rpi service.

Run with:  python main.py

Starts the command scheduler and serves the HTTP API on
HOST:PORT (see app/config.py).
"""

import atexit
import logging
import signal
import subprocess
import sys
from pathlib import Path

from app import create_app
from app.config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("rnk-rpi")


def _running_commit() -> str:
    """Best-effort git commit/dirty-state of this checkout, for startup logs."""
    try:
        result = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent), "describe", "--always", "--dirty"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unknown (git not available)"
    if result.returncode != 0 or not result.stdout:
        return "unknown (not a git checkout)"
    return result.stdout.decode("utf-8", "replace").strip()


def main() -> int:
    log.info("rnk-rpi starting, running commit %s", _running_commit())
    app = create_app()
    scheduler = app.extensions["scheduler"]
    audio_stream_server = app.extensions.get("audio_stream_server")

    def shutdown(_signum=None, _frame=None):
        log.info("shutting down")
        scheduler.shutdown()
        if audio_stream_server is not None:
            audio_stream_server.shutdown()

    def handle_signal(signum, frame):
        # Werkzeug's dev server keeps serving unless the process actually
        # exits, so the handler must terminate it, not just clean up.
        shutdown(signum, frame)
        sys.exit(0)

    atexit.register(shutdown)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    scheduler.start()
    if audio_stream_server is not None:
        audio_stream_server.start()
    log.info(
        "serving on http://%s:%s (POST /rnk/schedule)", Config.HOST, Config.PORT
    )

    try:
        app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
    finally:
        shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
