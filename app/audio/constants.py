"""Tunable parameters for audio playback."""

#: PCM format used for the ffmpeg (decode) -> aplay (ALSA output) pipeline.
SAMPLE_RATE = 44100
CHANNELS = 2

#: Maximum accepted size for an uploaded audio file, in bytes.
MAX_AUDIO_BYTES = 20 * 1024 * 1024  # 20 MB
