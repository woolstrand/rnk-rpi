"""Application package for the rnk-rpi robot controller."""

from flask import Flask

from .camera.config import load_camera_config
from .camera.ptz import PTZController
from .camera.snapshot import capture_frame
from .config import Config
from .motor.driver import MotorDriver
from .scheduler import CommandScheduler


def create_app(driver=None, scheduler=None, ptz_controller=None, snapshot_source=None):
    """Application factory.

    Args:
        driver: A MotorDriver (or compatible fake) instance. When omitted,
            a real MotorDriver is created. Tests inject a fake driver so the
            app can run on machines without GPIO hardware.
        scheduler: A pre-built CommandScheduler. When omitted, one is created
            using the given (or real) driver.
        ptz_controller: A PTZController (or compatible fake). When omitted,
            one is created from ``.env`` camera settings, if configured.
        snapshot_source: A callable ``(scaled: bool) -> bytes`` returning a
            JPEG frame. When omitted, one is created from ``.env`` camera
            settings, if configured.
    """
    app = Flask(__name__)
    app.config.from_object(Config)

    if driver is None:
        driver = MotorDriver()
    if scheduler is None:
        scheduler = CommandScheduler(driver)

    if ptz_controller is None and snapshot_source is None:
        camera_config = load_camera_config()
        if camera_config is not None:
            ptz_controller = PTZController(camera_config)
            snapshot_source = lambda scaled: capture_frame(  # noqa: E731
                camera_config.rtsp_url, scaled=scaled
            )

    app.extensions["scheduler"] = scheduler
    app.extensions["ptz_controller"] = ptz_controller
    app.extensions["snapshot_source"] = snapshot_source

    from .api.camera import camera_bp
    from .api.schedule import rnk_bp

    app.register_blueprint(rnk_bp)
    app.register_blueprint(camera_bp)

    return app
