"""Tunable parameters for the ONVIF/RTSP camera integration.

Pan/tilt/zoom values use ONVIF's normalized "generic" PTZ space, which
every ONVIF PTZ camera is required to support (as opposed to a
degrees/millimeters space, which is camera-specific and often absent).
"""

#: Absolute pan/tilt range (ONVIF generic space): -1.0 (one extreme) to
#: +1.0 (the other), 0.0 is center.
PAN_MIN = -1.0
PAN_MAX = 1.0
TILT_MIN = -1.0
TILT_MAX = 1.0

#: Absolute zoom range: 0.0 (fully wide) to 1.0 (fully tele).
ZOOM_MIN = 0.0
ZOOM_MAX = 1.0

#: Relative move deltas are clamped to the same +-1.0 span per axis.
RELATIVE_MIN = -1.0
RELATIVE_MAX = 1.0

#: Seconds to wait for ONVIF SOAP calls before giving up.
ONVIF_TIMEOUT_S = 5.0

#: Seconds to wait for ffmpeg to grab a single frame from the RTSP stream.
SNAPSHOT_TIMEOUT_S = 10.0

#: Downscaled snapshot dimensions (width, height), in pixels.
SCALED_WIDTH = 640
SCALED_HEIGHT = 480
