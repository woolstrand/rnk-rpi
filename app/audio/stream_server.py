"""TCP server that streams captured audio frames to a connected client (the rnk-agent).

Deliberately dumb: a raw, unframed stream of PCM bytes (format is fixed and
shared out-of-band via capture_constants.py / rnk_agent.config.AudioStreamConfig),
one client served at a time. Independent of the audio source implementation -
constructed with a ``source_factory`` callable, so a different source can be
swapped in later without any change here.
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Callable, Iterator, Optional

from . import capture_constants as constants
from .source import AudioSource, AudioSourceError

log = logging.getLogger(__name__)


class AudioStreamServer:
    def __init__(
        self,
        source_factory: Callable[[], AudioSource],
        prestart_check: Optional[Callable[[], None]] = None,
        host: str = constants.STREAM_HOST,
        port: int = constants.STREAM_PORT,
    ):
        """
        Args:
            source_factory: builds a fresh ``AudioSource`` for each connected
                client.
            prestart_check: optional callable run once in the background
                before the server starts listening (e.g. probing the camera
                for an audio track). If it raises ``AudioSourceError``, the
                server logs the error and never starts listening.
        """
        self._source_factory = source_factory
        self._prestart_check = prestart_check
        self._host = host
        self._port = port
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()

    def start(self) -> None:
        """Start the server on a background thread. Non-blocking, idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._shutdown_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="rnk-audio-stream-server", daemon=True
        )
        self._thread.start()

    def shutdown(self) -> None:
        self._shutdown_event.set()
        if self._sock is not None:
            self._sock.close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        if self._prestart_check is not None:
            try:
                self._prestart_check()
            except AudioSourceError as exc:
                log.error("audio streaming disabled: %s", exc)
                return

        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self._host, self._port))
            self._sock.listen(1)
            self._sock.settimeout(constants.ACCEPT_POLL_INTERVAL_S)
        except OSError:
            log.exception("could not bind audio stream server to %s:%s", self._host, self._port)
            return

        log.info("audio stream server listening on %s:%s", self._host, self._port)
        self._accept_loop()

    def _accept_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            log.info("audio stream client connected: %s:%s", *addr)
            self._serve_client(conn)
            log.info("audio stream client disconnected: %s:%s", *addr)

    def _serve_client(self, conn: socket.socket) -> None:
        try:
            source = self._source_factory()
        except AudioSourceError as exc:
            log.error("cannot start audio capture: %s", exc)
            conn.close()
            return

        try:
            frames: Iterator[bytes] = source.frames()
            for chunk in frames:
                if self._shutdown_event.is_set():
                    break
                conn.sendall(chunk)
        except OSError:
            pass  # client disconnected mid-stream
        finally:
            source.close()
            conn.close()
