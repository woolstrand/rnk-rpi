"""Application package for the rnk-rpi robot controller."""

import logging

from flask import Flask

from .audio.player import play_file
from .audio.source import CameraAudioSource, probe_camera_audio
from .audio.stream_server import AudioStreamServer
from .camera.config import load_camera_config
from .camera.ptz import PTZController
from .camera.snapshot import capture_frame
from .config import Config
from .motor.driver import MotorDriver
from .scheduler import CommandScheduler

log = logging.getLogger(__name__)


def create_app(
    driver=None,
    scheduler=None,
    ptz_controller=None,
    snapshot_source=None,
    audio_player=None,
    audio_stream_server=None,
):
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
        audio_player: A callable ``(data: bytes) -> None`` that plays an
            audio file on the default output. When omitted, the real
            ffmpeg/aplay-based player is used.
        audio_stream_server: An AudioStreamServer (or compatible fake) that
            streams captured audio to the agent. When omitted, one is built
            from ``.env`` camera settings (extracting audio from the
            camera's RTSP stream), if configured; it isn't started here -
            see main.py.
    """
    app = Flask(__name__)
    app.config.from_object(Config)

    if audio_player is None:
        audio_player = play_file

    if driver is None:
        driver = MotorDriver()
    if scheduler is None:
        scheduler = CommandScheduler(driver)

    camera_config = None
    if ptz_controller is None and snapshot_source is None:
        camera_config = load_camera_config()
        if camera_config is not None:
            ptz_controller = PTZController(camera_config)
            snapshot_source = lambda scaled: capture_frame(  # noqa: E731
                camera_config.rtsp_url, scaled=scaled
            )

    if audio_stream_server is None:
        if camera_config is None:
            camera_config = load_camera_config()
        if camera_config is not None:
            audio_stream_server = AudioStreamServer(
                source_factory=lambda: CameraAudioSource(camera_config.rtsp_url),
                prestart_check=lambda: probe_camera_audio(camera_config.rtsp_url),
            )
        else:
            log.info("no camera configured; audio capture/streaming disabled")

    app.extensions["scheduler"] = scheduler
    app.extensions["ptz_controller"] = ptz_controller
    app.extensions["snapshot_source"] = snapshot_source
    app.extensions["audio_player"] = audio_player
    app.extensions["audio_stream_server"] = audio_stream_server

    from .api.audio import audio_bp
    from .api.camera import camera_bp
    from .api.schedule import rnk_bp

    app.register_blueprint(rnk_bp)
    app.register_blueprint(audio_bp)
    app.register_blueprint(camera_bp)

    return app
