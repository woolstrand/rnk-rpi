"""Tunable parameters for continuous audio capture + streaming to the agent."""

#: TCP server the rnk-agent connects to for the continuous raw-PCM audio feed.
STREAM_HOST = "0.0.0.0"
STREAM_PORT = 5001

#: PCM format streamed to the agent: 16 kHz mono 16-bit signed little-endian.
#: 16 kHz is the highest rate webrtcvad (used agent-side) accepts that still
#: keeps bandwidth low. Must match rnk_agent.config.AudioStreamConfig on the Mac.
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes per sample (16-bit signed PCM)

#: Frame size ffmpeg's stdout is read in, matched to the agent's default VAD
#: frame duration (20 ms) so frames line up without extra buffering on either end.
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * SAMPLE_WIDTH * CHANNELS

#: How long to wait for ffprobe to report the camera stream's audio track
#: before giving up (camera unreachable, or genuinely has no microphone).
PROBE_TIMEOUT_S = 5.0

#: How often the accept loop wakes up to check for a shutdown request.
ACCEPT_POLL_INTERVAL_S = 1.0
