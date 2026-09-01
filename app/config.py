"""Runtime configuration for the rnk-rpi service."""


class Config:
    """Flask application configuration.

    The service binds to all interfaces so the robot can be commanded
    from other devices on the local network.
    """

    HOST = "0.0.0.0"
    PORT = 5000
    DEBUG = False
