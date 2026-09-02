"""Environment-based configuration for the ONVIF/RTSP camera integration.

The camera's IP address and credentials live in a ``.env`` file (see
``.env.example`` at the repo root) and are loaded via python-dotenv, so
nothing sensitive is hardcoded or committed to the repo.
"""

import os
from dataclasses import dataclass
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class CameraConfig:
    ip: str
    onvif_port: int
    username: str
    password: str
    rtsp_url: str
    onvif_timeout_s: float


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def _build_rtsp_url(ip: str, username: str, password: str) -> str:
    port = _env_int("CAMERA_RTSP_PORT", 554)
    path = os.environ.get("CAMERA_RTSP_PATH", "stream1").lstrip("/")
    if username or password:
        auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    else:
        auth = ""
    return f"rtsp://{auth}{ip}:{port}/{path}"


def load_camera_config():
    """Build a :class:`CameraConfig` from the environment.

    Returns:
        A ``CameraConfig``, or ``None`` if ``CAMERA_IP`` is not set (i.e.
        no camera is configured for this deployment).
    """
    ip = os.environ.get("CAMERA_IP")
    if not ip:
        return None

    username = os.environ.get("CAMERA_USERNAME", "")
    password = os.environ.get("CAMERA_PASSWORD", "")
    rtsp_url = os.environ.get("CAMERA_RTSP_URL") or _build_rtsp_url(
        ip, username, password
    )

    return CameraConfig(
        ip=ip,
        onvif_port=_env_int("CAMERA_ONVIF_PORT", 80),
        username=username,
        password=password,
        rtsp_url=rtsp_url,
        onvif_timeout_s=float(os.environ.get("CAMERA_ONVIF_TIMEOUT_S", "5")),
    )
