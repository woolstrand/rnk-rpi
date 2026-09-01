"""Entry point for the rnk-rpi service.

Run with:  python main.py

Starts the command scheduler and serves the HTTP API on
HOST:PORT (see app/config.py).
"""

import atexit
import logging
import signal
import sys

from app import create_app
from app.config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("rnk-rpi")


def main() -> int:
    app = create_app()
    scheduler = app.extensions["scheduler"]

    def shutdown(_signum=None, _frame=None):
        log.info("shutting down")
        scheduler.shutdown()

    atexit.register(shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    scheduler.start()
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
