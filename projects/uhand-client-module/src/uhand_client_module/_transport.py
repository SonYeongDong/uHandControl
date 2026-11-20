"""One socket, one receiver thread, independently waiting request callers."""
from dataclasses import dataclass, field
import socket
import threading
import time

from ._protocol import MAX_FRAME_BYTES, MAX_REQUEST_ID, request_frame, response_frame, response_outcome
from ._validation import endpoint
from .errors import (
    AlreadyConnectedError, ConnectionFailedError, DisconnectedError,
    NotConnectedError, ProtocolError, RemoteError, RequestTimeoutError,
)

CONNECT_TIMEOUT = 5.0
RESPONSE_TIMEOUT = 5.0
SOCKET_IO_TIMEOUT = 1.0
HEARTBEAT_INTERVAL = 1.0
HEARTBEAT_TIMEOUT = 2.0


@dataclass
class _Pending:
    method: str
    done: threading.Event = field(default_factory=threading.Event)
    result: object = None
    error: Exception | None = None


class _Session:
    def __init__(self, sock):
        self._socket = sock
        self._state = threading.Lock()
        self._send = threading.Lock()
        self._pending = {}
        self._next_id = 1
        self._closed = None
        self._stop = threading.Event()
        self._last_response = time.monotonic()
        self._reader = threading.Thread(target=self._receive, name="uHandClient-receiver", daemon=True)
        self._reader.start()

    @property
    def closed(self):
        with self._state:
            return self._closed is not None

    def close(self, error=None, unless_done=None):
        """Fail all waiting calls, without ever retrying a command."""
        if error is None:
            error = DisconnectedError("Connection closed; in-flight commands may still execute.")
        with self._state:
            if self._closed is not None or (unless_done is not None and unless_done.done.is_set()):
                return
            self._closed = error
            self._stop.set()
            for pending in self._pending.values():
                # Each caller receives an exception instance with its own traceback.
                pending.error = type(error)(*error.args)
                pending.done.set()
            self._pending.clear()
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._socket.close()

    def request(self, method, params, timeout):
        deadline = time.monotonic() + timeout
        pending = _Pending(method)
        with self._state:
            if self._closed is not None:
                raise DisconnectedError("Connection is closed.")
            if self._next_id > MAX_REQUEST_ID:
                raise ProtocolError("Request ID space exhausted; disconnect and reconnect.")
            rid = self._next_id
            self._next_id += 1
            self._pending[rid] = pending
        frame = request_frame(rid, method, params)
        acquired = self._send.acquire(timeout=max(0.0, deadline - time.monotonic()))
        if not acquired:
            self.close(RequestTimeoutError("Timed out waiting to send; connection closed."), pending)
        else:
            try:
                if not self.closed:
                    self._socket.sendall(frame)
            except OSError as exc:
                self.close(DisconnectedError(f"Send failed: {exc}. Execution outcome may be unknown."))
            finally:
                self._send.release()
        if not pending.done.wait(max(0.0, deadline - time.monotonic())):
            self.close(RequestTimeoutError(
                f"{method} response timed out; connection closed. The command may still execute."
            ), pending)
        if pending.error is not None:
            raise pending.error
        return pending.result

    def _deliver(self, frame):
        value = response_frame(frame)
        with self._state:
            if self._closed is not None:
                return
            rid = value["request_id"]
            pending = self._pending.get(rid)
            if pending is None:
                raise ProtocolError("Unknown or duplicate response request_id.")
            result, error = response_outcome(value, pending.method)
            self._last_response = time.monotonic()
            del self._pending[rid]
            pending.result = result
            pending.error = error
            pending.done.set()

    def start_monitor(self):
        threading.Thread(target=self._monitor, name="uHandClient-heartbeat", daemon=True).start()

    def _monitor(self):
        while not self._stop.is_set():
            with self._state:
                due = self._last_response + HEARTBEAT_INTERVAL
            if self._stop.wait(max(0, due - time.monotonic())):
                return
            with self._state:
                if time.monotonic() < self._last_response + HEARTBEAT_INTERVAL:
                    continue
            try:
                # Protocol v2 permits read-only status requests even during a long output.
                self.request("GetStatus", {}, HEARTBEAT_TIMEOUT)
            except RemoteError:
                continue  # A valid error response also proves the peer is reachable.
            except (DisconnectedError, ProtocolError, RequestTimeoutError) as exc:
                self.close(exc)
                return

    def _receive(self):
        buffer = bytearray()
        try:
            while not self.closed:
                try:
                    data = self._socket.recv(8192)
                except socket.timeout:
                    continue
                if not data:
                    if buffer:
                        raise ProtocolError("Connection closed during a response frame.")
                    self.close(DisconnectedError("Server closed the connection; execution outcome may be unknown."))
                    return
                buffer.extend(data)
                while True:
                    boundary = buffer.find(b"\n")
                    if boundary < 0:
                        break
                    if boundary + 1 > MAX_FRAME_BYTES:
                        raise ProtocolError("Response exceeds the frame byte limit.")
                    frame = bytes(buffer[:boundary])
                    del buffer[:boundary + 1]
                    self._deliver(frame)
                if len(buffer) >= MAX_FRAME_BYTES:
                    raise ProtocolError("Unterminated response exceeds the frame byte limit.")
        except ProtocolError as exc:
            self.close(exc)
        except OSError as exc:
            self.close(DisconnectedError(f"Receive failed: {exc}. Execution outcome may be unknown."))


class _Client:
    """Private session owner; the supported user interface is the six module functions."""

    def __init__(self):
        self._lifecycle = threading.Lock()
        self._session = None

    def connect(self, ip, port):
        address = endpoint(ip, port)
        with self._lifecycle:
            if self._session is not None and not self._session.closed:
                raise AlreadyConnectedError("Already connected. Call Disconnect() before Connect().")
            self._session = None
            deadline = time.monotonic() + CONNECT_TIMEOUT
            family = socket.AF_INET if address.version == 4 else socket.AF_INET6
            sock = socket.socket(family, socket.SOCK_STREAM)
            try:
                sock.settimeout(max(0.001, deadline - time.monotonic()))
                sock.connect((str(address), port))
                sock.settimeout(SOCKET_IO_TIMEOUT)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError as exc:
                sock.close()
                raise ConnectionFailedError(f"Cannot connect to {ip}:{port}: {exc}") from exc
            session = _Session(sock)
            try:
                session.request("Hello", {}, max(0.0, deadline - time.monotonic()))
                if session.closed:
                    raise DisconnectedError("Server closed the connection during Connect().")
            except Exception:
                session.close()
                raise
            self._session = session
            session.start_monitor()

    def disconnect(self):
        with self._lifecycle:
            session, self._session = self._session, None
            if session is not None:
                session.close()

    def request(self, method, params):
        with self._lifecycle:
            session = self._session
            if session is None or session.closed:
                raise NotConnectedError("Call Connect(IP, Port) before sending commands.")
        # No lifecycle/output lock is held while waiting for completion.
        timeout = RESPONSE_TIMEOUT + (0 if params.get("Continuous", False) else params.get("RunningTime", 0) / 1000.0)
        return session.request(method, params, timeout)
