"""Runtime configuration for the rnk-rpi service."""


class Config:
    """Flask application configuration.

    The service binds to all interfaces so the robot can be commanded
    from other devices on the local network.
    """

    HOST = "0.0.0.0"
    PORT = 5000
    DEBUG = False

    # Hard cap on request body size (enforced by Flask/Werkzeug before the
    # view runs); mainly guards the audio upload endpoint against
    # oversized/DoS-y uploads. Keep in sync with app/audio/constants.py.
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB
