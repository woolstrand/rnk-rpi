"""ONVIF PTZ control: pan/tilt/zoom a camera over the network.

``onvif-zeep`` (the SOAP/WSDL ONVIF client) is imported lazily, inside
:meth:`PTZController._connect`, so this module — and the rest of the app —
can be imported on machines that don't have it installed, and so a camera
that's offline at startup doesn't prevent the service from starting.

PTZ moves use ONVIF's normalized "generic" space (pan/tilt in -1.0..1.0,
zoom in 0.0..1.0), which every ONVIF PTZ camera is required to expose,
rather than a camera-specific degrees/millimeters space.
"""

import logging
import threading

log = logging.getLogger(__name__)


class PTZError(RuntimeError):
    """Raised when a PTZ operation cannot be carried out."""


class PTZController:
    """Talks ONVIF PTZ to a single camera. Connects lazily, on first use."""

    def __init__(self, config):
        self._config = config
        self._lock = threading.Lock()
        self._ptz = None
        self._profile_token = None
        self._supports_absolute = False
        self._supports_relative = False
        self._supports_home = False

    def _connect(self) -> None:
        """Establish the ONVIF session and probe PTZ capabilities. Idempotent."""
        if self._ptz is not None:
            return
        from onvif import ONVIFCamera  # lazy: only needed once a camera is used

        camera = ONVIFCamera(
            self._config.ip,
            self._config.onvif_port,
            self._config.username,
            self._config.password,
        )
        media = camera.create_media_service()
        ptz = camera.create_ptz_service()
        profiles = media.GetProfiles()
        if not profiles:
            raise PTZError("camera reported no media profiles")
        profile = profiles[0]

        supports_absolute = False
        supports_relative = False
        supports_home = False
        ptz_config = getattr(profile, "PTZConfiguration", None)
        config_token = getattr(ptz_config, "token", None) if ptz_config else None
        if config_token:
            try:
                options = ptz.GetConfigurationOptions(
                    {"ConfigurationToken": config_token}
                )
                spaces = getattr(options, "Spaces", None)
                supports_absolute = bool(
                    getattr(spaces, "AbsolutePanTiltPositionSpace", None)
                )
                supports_relative = bool(
                    getattr(spaces, "RelativePanTiltTranslationSpace", None)
                )
            except Exception:
                log.exception(
                    "could not read PTZ configuration options; "
                    "assuming relative-only support"
                )
                supports_relative = True
        try:
            nodes = ptz.GetNodes()
            supports_home = bool(nodes) and bool(
                getattr(nodes[0], "HomeSupported", False)
            )
        except Exception:
            log.exception("could not read PTZ node capabilities")

        self._ptz = ptz
        self._profile_token = profile.token
        self._supports_absolute = supports_absolute
        self._supports_relative = supports_relative
        self._supports_home = supports_home
        log.info(
            "PTZ connected to %s: absolute=%s relative=%s home=%s",
            self._config.ip,
            supports_absolute,
            supports_relative,
            supports_home,
        )

    def capabilities(self) -> dict:
        """Which PTZ operations the camera supports, e.g. for the status endpoint."""
        with self._lock:
            self._connect()
            return {
                "absolute": self._supports_absolute,
                "relative": self._supports_relative,
                "home": self._supports_home,
            }

    def absolute_move(self, pan: float, tilt: float, zoom: float = None) -> None:
        """Move to an absolute pan/tilt (and optional zoom) position."""
        with self._lock:
            self._connect()
            if not self._supports_absolute:
                raise PTZError("camera does not support absolute PTZ moves")
            request = self._ptz.create_type("AbsoluteMove")
            request.ProfileToken = self._profile_token
            position = {"PanTilt": {"x": pan, "y": tilt}}
            if zoom is not None:
                position["Zoom"] = {"x": zoom}
            request.Position = position
            self._ptz.AbsoluteMove(request)

    def relative_move(self, pan: float, tilt: float, zoom: float = None) -> None:
        """Move by a pan/tilt (and optional zoom) delta from the current position."""
        with self._lock:
            self._connect()
            if not self._supports_relative:
                raise PTZError("camera does not support relative PTZ moves")
            request = self._ptz.create_type("RelativeMove")
            request.ProfileToken = self._profile_token
            translation = {"PanTilt": {"x": pan, "y": tilt}}
            if zoom is not None:
                translation["Zoom"] = {"x": zoom}
            request.Translation = translation
            self._ptz.RelativeMove(request)

    def stop(self) -> None:
        """Stop any pan/tilt/zoom movement currently in progress."""
        with self._lock:
            self._connect()
            self._ptz.Stop(
                {"ProfileToken": self._profile_token, "PanTilt": True, "Zoom": True}
            )

    def home(self) -> None:
        """Reset to the camera's "home"/central position.

        Prefers the ONVIF ``GotoHomePosition`` operation (a camera-defined
        preset); falls back to an absolute move to the center of the
        pan/tilt range if the camera doesn't support a home preset.
        """
        with self._lock:
            self._connect()
            if self._supports_home:
                request = self._ptz.create_type("GotoHomePosition")
                request.ProfileToken = self._profile_token
                self._ptz.GotoHomePosition(request)
                return
            if self._supports_absolute:
                request = self._ptz.create_type("AbsoluteMove")
                request.ProfileToken = self._profile_token
                request.Position = {"PanTilt": {"x": 0.0, "y": 0.0}}
                self._ptz.AbsoluteMove(request)
                return
            raise PTZError(
                "camera supports neither a home preset nor absolute PTZ moves"
            )

    def status(self) -> dict:
        """Current pan/tilt/zoom position and move state, as reported by the camera."""
        with self._lock:
            self._connect()
            status = self._ptz.GetStatus({"ProfileToken": self._profile_token})
            position = getattr(status, "Position", None)
            pan_tilt = getattr(position, "PanTilt", None) if position else None
            zoom = getattr(position, "Zoom", None) if position else None
            move_status = getattr(status, "MoveStatus", None)
            return {
                "pan": getattr(pan_tilt, "x", None) if pan_tilt else None,
                "tilt": getattr(pan_tilt, "y", None) if pan_tilt else None,
                "zoom": getattr(zoom, "x", None) if zoom else None,
                "moving": getattr(move_status, "PanTilt", None) == "MOVING",
            }
