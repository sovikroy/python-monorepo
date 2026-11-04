"""A tiny broker spoken over plain TCP, using only the standard library.

It needs no third-party server or client library, which makes it handy for local
development, CI and small deployments. Run the server with ``apps/tcp-broker``
and point services at ``tcp://<host>:<port>``. Queues are kept in the server's
memory, so messages are lost if the server restarts; use Redis or RabbitMQ when
that matters.

Wire protocol: one JSON object per line in each direction.

    -> {"op": "publish", "topic": "t", "message": "..."}   <- {"ok": true}
    -> {"op": "receive", "topic": "t", "timeout": 1.0}     <- {"ok": true, "message": "..." | null}
    -> {"op": "ping"}                                      <- {"ok": true}
    any error                                              <- {"ok": false, "error": "..."}
"""

from __future__ import annotations

import contextlib
import json
import logging
import socket
import socketserver
import threading
import time
from collections import deque
from typing import Any, Self
from urllib.parse import urlsplit

from messaging.broker import Broker, BrokerError

log = logging.getLogger(__name__)

DEFAULT_PORT = 7000
MAX_LINE = 16 * 1024 * 1024  # refuse absurdly large frames instead of buffering forever
NETWORK_GRACE = 5.0  # extra seconds a client waits beyond the receive timeout


# --------------------------------------------------------------------- client


class TcpBroker(Broker):
    """Client for :class:`TcpBrokerServer`. Thread-safe; reconnects once on a dropped link."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, connect_timeout: float = 5.0) -> None:
        self._address = (host, port)
        self._connect_timeout = connect_timeout
        self._sock: socket.socket | None = None
        self._file: Any = None
        self._lock = threading.Lock()

    @classmethod
    def from_url(cls, url: str) -> Self:
        parts = urlsplit(url)
        if not parts.hostname:
            raise BrokerError(f"tcp broker URL needs a host, e.g. tcp://localhost:7000: {url!r}")
        return cls(parts.hostname, parts.port or DEFAULT_PORT)

    def publish(self, topic: str, message: str) -> None:
        self._call({"op": "publish", "topic": topic, "message": message}, wait=0.0)

    def receive(self, topic: str, timeout: float = 1.0) -> str | None:
        reply = self._call({"op": "receive", "topic": topic, "timeout": timeout}, wait=timeout)
        message = reply.get("message")
        return message if isinstance(message, str) else None

    def ping(self) -> None:
        self._call({"op": "ping"}, wait=0.0)

    def close(self) -> None:
        with self._lock:
            self._disconnect()

    def _call(self, request: dict[str, Any], wait: float) -> dict[str, Any]:
        frame = (json.dumps(request) + "\n").encode()
        with self._lock:
            # A request that is not a receive is safe to resend; a receive is too,
            # because the server re-queues a message it could not deliver.
            for attempt in (1, 2):
                try:
                    sock, file = self._connection()
                    sock.settimeout(wait + NETWORK_GRACE)
                    sock.sendall(frame)
                    line = file.readline(MAX_LINE)
                    if not line:
                        raise ConnectionError("tcp broker closed the connection")
                    break
                except OSError:
                    self._disconnect()
                    if attempt == 2:
                        raise
        reply: dict[str, Any] = json.loads(line)
        if not reply.get("ok"):
            raise BrokerError(f"tcp broker error: {reply.get('error')}")
        return reply

    def _connection(self) -> tuple[socket.socket, Any]:
        if self._sock is None:
            self._sock = socket.create_connection(self._address, timeout=self._connect_timeout)
            self._file = self._sock.makefile("rb")
        return self._sock, self._file

    def _disconnect(self) -> None:
        sock, self._sock, self._file = self._sock, None, None
        if sock is not None:
            sock.close()


# --------------------------------------------------------------------- server


class _Topic:
    def __init__(self) -> None:
        self.items: deque[str] = deque()
        self.ready = threading.Condition()

    def put(self, message: str, front: bool = False) -> None:
        with self.ready:
            if front:
                self.items.appendleft(message)
            else:
                self.items.append(message)
            self.ready.notify()

    def get(self, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        with self.ready:
            while not self.items:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.ready.wait(remaining)
            return self.items.popleft()


class _Handler(socketserver.StreamRequestHandler):
    server: TcpBrokerServer

    def setup(self) -> None:
        super().setup()
        self.server.track(self.connection, add=True)

    def finish(self) -> None:
        self.server.track(self.connection, add=False)
        super().finish()

    def handle(self) -> None:
        while True:
            try:
                line = self.rfile.readline(MAX_LINE)
            except OSError:
                return
            if not line:
                return
            reply, undelivered = self.server.dispatch(line)
            try:
                self.wfile.write((json.dumps(reply) + "\n").encode())
                self.wfile.flush()
            except OSError:
                # The client went away while we were answering: give the message back.
                if undelivered is not None:
                    self.server.requeue(*undelivered)
                return


class TcpBrokerServer(socketserver.ThreadingTCPServer):
    """Holds one FIFO queue per topic and serves :class:`TcpBroker` clients."""

    daemon_threads = True
    allow_reuse_address = True
    max_receive_timeout = 30.0

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        super().__init__((host, port), _Handler)
        self._topics: dict[str, _Topic] = {}
        self._topics_lock = threading.Lock()
        self._clients: set[socket.socket] = set()

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def pending(self, topic: str) -> int:
        return len(self._topic(topic).items)

    def track(self, sock: socket.socket, add: bool) -> None:
        with self._topics_lock:
            if add:
                self._clients.add(sock)
            else:
                self._clients.discard(sock)

    def server_close(self) -> None:
        """Stop listening and drop every client, as a process exit would."""
        super().server_close()
        with self._topics_lock:
            clients, self._clients = self._clients, set()
        for sock in clients:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    def requeue(self, topic: str, message: str) -> None:
        self._topic(topic).put(message, front=True)

    def dispatch(self, line: bytes) -> tuple[dict[str, Any], tuple[str, str] | None]:
        """Run one request. Returns the reply and, for a receive, what was taken."""
        try:
            request = json.loads(line)
            op = request.get("op")
            if op == "ping":
                return {"ok": True}, None
            topic = request["topic"]
            if not isinstance(topic, str) or not topic:
                raise ValueError("topic must be a non-empty string")
            if op == "publish":
                message = request["message"]
                if not isinstance(message, str):
                    raise ValueError("message must be a string")
                self._topic(topic).put(message)
                return {"ok": True}, None
            if op == "receive":
                timeout = float(request.get("timeout", 1.0))
                timeout = min(max(timeout, 0.0), self.max_receive_timeout)
                message = self._topic(topic).get(timeout)
                taken = None if message is None else (topic, message)
                return {"ok": True, "message": message}, taken
            raise ValueError(f"unknown op {op!r}")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            return {"ok": False, "error": str(exc) or type(exc).__name__}, None

    def _topic(self, name: str) -> _Topic:
        with self._topics_lock:
            topic = self._topics.get(name)
            if topic is None:
                topic = self._topics[name] = _Topic()
            return topic
