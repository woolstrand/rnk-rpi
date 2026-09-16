"""Tunable parameters for audio playback."""

#: PCM format used for the ffmpeg (decode) -> aplay (ALSA output) pipeline.
SAMPLE_RATE = 44100
CHANNELS = 2

#: Maximum accepted size for an uploaded audio file, in bytes.
MAX_AUDIO_BYTES = 20 * 1024 * 1024  # 20 MB

#: Default/allowed range for the optional "volume" field on POST /rnk/audio/play
#: (a gain multiplier applied by ffmpeg during decode; 1.0 = unchanged).
DEFAULT_VOLUME = 1.0
MIN_VOLUME = 0.0
MAX_VOLUME = 4.0
