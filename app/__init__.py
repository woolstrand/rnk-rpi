"""Application package for the rnk-rpi robot controller."""

from flask import Flask

from .config import Config
from .motor.driver import MotorDriver
from .scheduler import CommandScheduler


def create_app(driver=None, scheduler=None):
    """Application factory.

    Args:
        driver: A MotorDriver (or compatible fake) instance. When omitted,
            a real MotorDriver is created. Tests inject a fake driver so the
            app can run on machines without GPIO hardware.
        scheduler: A pre-built CommandScheduler. When omitted, one is created
            using the given (or real) driver.
    """
    app = Flask(__name__)
    app.config.from_object(Config)

    if driver is None:
        driver = MotorDriver()
    if scheduler is None:
        scheduler = CommandScheduler(driver)

    app.extensions["scheduler"] = scheduler

    from .api.schedule import rnk_bp

    app.register_blueprint(rnk_bp)

    return app
