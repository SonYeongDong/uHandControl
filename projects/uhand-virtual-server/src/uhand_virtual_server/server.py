"""Threaded single-owner server, independent of GUI and physical hardware."""
from collections import deque
import copy
import socket
import threading
import time

from uhand_server_lifecycle import GAP_MS, HOME_MS, MELODIES, Lifecycle, enable_keepalive

from uhand_server_lifecycle import status_reply

from .protocol import (
    CommandError, EMPTY_STATUS, MAX_FRAME, PULSE_NAMES,
    decode, response, validate_bind, validate_request,
)


class UnavailableAudio:
    description = "오디오 출력 미사용"
    def play(self, frequency, duration, cancel):
        raise CommandError("DEVICE_ERROR", "No audio backend is configured.")
    def start(self, frequency):
        raise CommandError("DEVICE_ERROR", "No audio backend is configured.")
    def stop(self):pass


class Connection:
    def __init__(self, server, sock, address):
        self.server, self.sock, self.address = server, sock, address
        self.send_lock = threading.Lock()
        self.closed = threading.Event()
        self.seen = set()
        self.admitted = False

    def send(self, rid, result=None, error=None):
        data = response(rid, result, error)
        with self.send_lock:
            if self.closed.is_set():
                return
            try:
                self.sock.sendall(data)
            except OSError:
                self.close()

    def close(self):
        self.closed.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()

    def run(self):
        buffer = bytearray()
        hello_deadline = time.monotonic() + 5
        try:
            while not self.server.stopping.is_set() and not self.closed.is_set():
                if not self.admitted and time.monotonic() > hello_deadline:
                    break
                try:
                    data = self.sock.recv(8192)
                except socket.timeout:
                    continue
                if not data:
                    break
                buffer.extend(data)
                while b"\n" in buffer:
                    end = buffer.index(b"\n")
                    if end + 1 > MAX_FRAME:
                        raise ValueError("Frame exceeds 65536 bytes.")
                    frame = bytes(buffer[:end])
                    del buffer[:end + 1]
                    request = decode(frame)
                    rid = request["request_id"]
                    if rid in self.seen:
                        raise ValueError("Duplicate request ID.")
                    self.seen.add(rid)
                    try:
                        method, params = validate_request(request)
                        self.server.dispatch(self, rid, method, params)
                    except CommandError as exc:
                        self.send(rid, error=exc)
                        self.server.log(f"{exc.code} · {exc.message}", "error")
                        if not self.admitted and self.server.owner is not self:
                            return
                    if self.closed.is_set():
                        return
                if len(buffer) >= MAX_FRAME:
                    raise ValueError("Unterminated frame exceeds limit.")
        except (OSError, ValueError) as exc:
            if not self.closed.is_set() and not self.server.stopping.is_set():
                self.server.log(f"연결 종료 · {exc}", "error")
        finally:
            self.close()
            self.server.release(self)


def interpolate_pose(motion, now):
    source, target, start, duration = motion
    fraction = max(0.0, min(1.0, (now - start) / duration))
    return [a + (b - a) * fraction for a, b in zip(source, target)]


class VirtualServer:
    def __init__(self, host="127.0.0.1", port=5000, audio=None):
        self.address = validate_bind(host, port)
        self.host, self.port = str(self.address), port
        if audio is None:
            from .audio import create_audio
            audio = create_audio()
        self.audio = audio
        self._notice_note_index = None
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.lifecycle = Lifecycle(self)
        self.abort_output = threading.Event()
        self.output_done = threading.Event()
        self.output_done.set()
        self.owner = None
        self.connections = set()
        self.threads = set()
        self.listener = None
        self.accept_thread = None
        self.status = copy.deepcopy(EMPTY_STATUS)
        self.display = [1500.0] * 6
        self.motion = None
        self.active = None
        self.active_params = None
        self.busy = False
        self.buzzer_output = None
        self.events = deque(maxlen=200)
        self.event_number = 0
        self.last_error_id = 0
        self.last_error = ""
        self.listening = False
        self.powered_off = False

    def log(self, message, level="info"):
        with self.lock:
            self.event_number += 1
            self.events.append((self.event_number, time.strftime("%H:%M:%S"), level, message))
            if level == "error":
                self.last_error = message
                self.last_error_id = self.event_number

    def clear_events(self):
        with self.lock:
            self.events.clear()
            return self.event_number

    def stop_listening(self):
        """Simulate losing power without running the normal disconnect sequence."""
        with self.lock:
            if not self.listening:
                return
            frozen_pose = self._display_at(time.monotonic())
            last_completed = copy.deepcopy(self.status)
            self.display, self.motion = frozen_pose, None
            self.listening = False
            self.powered_off = True
            self.owner = None
            self.listener.close()
            for connection in tuple(self.connections):
                connection.close()
            self.lifecycle.cancel()
            self.abort_output.set()

        # The audio device is owned by an output or chime worker until it exits.
        # Wait outside the state lock so both can complete cancellation.
        self.output_done.wait()
        try:
            with self.lifecycle.serial:
                if hasattr(self.audio, "close"):
                    self.audio.close()
                elif hasattr(self.audio, "stop"):
                    self.audio.stop()
        finally:
            self.accept_thread.join()
            with self.lock:
                workers = tuple(self.threads)
            for worker in workers:
                worker.join()
            with self.lock:
                self.display, self.motion = frozen_pose, None
                self.status = last_completed
                self.buzzer_output = None
                self.lifecycle.error = None
                self.last_error = ""
                self.listener = None
                self.log("가상 로봇손 전원 꺼짐")

    def start(self, host=None, port=None, *, background=False):
        with self.lock:
            if self.listener is not None or self.stopping.is_set():
                raise RuntimeError("Create a new server instance to start a fresh session.")
            port = self.port if port is None else port
            address = validate_bind(self.host if host is None else host, port)
            sock = socket.socket(socket.AF_INET if address.version == 4 else socket.AF_INET6, socket.SOCK_STREAM)
            try:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    # Allow immediate power-on after closing a client in TIME_WAIT.
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((str(address), port))
                sock.listen(8)
                sock.settimeout(0.2)
            except OSError:
                sock.close()
                raise
            self.address, self.host = address, str(address)
            self.listener = sock
            self.port = sock.getsockname()[1]
            self.listening = True
            self.powered_off = False
            self.last_error = ""
            self.log(f"서버 시작 · {self.host}:{self.port}")
            self.accept_thread = threading.Thread(target=self._accept, args=(sock,), name="uHandServer-accept", daemon=True)
            ready = self.lifecycle.begin("startup")
            self.accept_thread.start()
        if not background:
            ready.wait()
            if self.lifecycle.error:
                raise RuntimeError(self.lifecycle.error)

    def _accept(self, listener):
        while self.listener is listener and self.listening and not self.stopping.is_set():
            try:
                sock, address = listener.accept()
                sock.settimeout(0.5)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except socket.timeout:
                continue
            except OSError:
                return
            enable_keepalive(sock)
            connection = Connection(self, sock, address)
            with self.lock:
                if self.listener is not listener or not self.listening or len(self.connections) >= 16:
                    connection.close()
                    continue
                self.connections.add(connection)
            self._spawn(connection.run, "uHandServer-connection")

    def _spawn(self, function, name):
        def run():
            try:
                function()
            finally:
                with self.lock:
                    self.threads.discard(threading.current_thread())
        worker = threading.Thread(target=run, name=name, daemon=True)
        with self.lock:
            self.threads.add(worker)
        worker.start()

    @staticmethod
    def _device_error(message):
        return CommandError("DEVICE_ERROR", message)

    def release(self, connection):
        with self.lock:
            self.connections.discard(connection)
            if self.owner is connection:
                self.owner = None
                if self.listening and not self.stopping.is_set():
                    self.abort_output.set()
                    self.lifecycle.begin("disconnect")

    def dispatch(self, connection, rid, method, params):
        with self.lock:
            if self.lifecycle.error:
                raise CommandError("DEVICE_ERROR", self.lifecycle.error)
            if not self.listening or self.lifecycle.phase:
                raise CommandError("BUSY", "Server initialization or shutdown is in progress.")
            if method == "Hello":
                if connection.admitted:
                    raise CommandError("INVALID_ARGUMENT", "Hello already completed.")
                if self.owner is not None:
                    raise CommandError("BUSY", "Another Client owns the server.")
                self.owner = connection
                self.lifecycle.begin("connect", connection, rid)
                return
            if self.owner is not connection:
                raise CommandError("INVALID_ARGUMENT", "Send Hello before any command.")
            if method == "GetStatus":
                result = status_reply(copy.deepcopy(self.status), params)
            else:
                if self.busy:
                    raise CommandError("BUSY", "An output is already running.")
                if not self.listening:
                    raise CommandError("BUSY", "Server is shutting down.")
                self.busy = True
                self.output_done.clear()
                self.active = method
                self.active_params = dict(params)
                self.last_error = ""
                self.log(f"{method} 시작")
                self._spawn(lambda: self._execute(connection, rid, method, params), "uHandServer-output")
                return
        connection.send(rid, result)

    def _execute(self, connection, rid, method, params):
        error = None
        try:
            duration = params.get("RunningTime", 0) / 1000
            if method == "SetuHandPulse":
                target = [params[name] for name in PULSE_NAMES]
                with self.lock:
                    started = time.monotonic()
                    self.motion = (self._display_at(started), target, started, duration)
                deadline = started + duration
                while (remaining := deadline - time.monotonic()) > 0:
                    if self.abort_output.wait(remaining):
                        raise CommandError("DEVICE_ERROR", "Server stopped before completion.")
                with self.lock:
                    self.display = list(target)
                    self.motion = None
                    self.status["TargetPulses"] = list(target)
                    self.status["PulseRunningTime"] = params["RunningTime"]
            elif method == "SetuHandBuzzer":
                frequency, continuous = params["Frequency"], params["Continuous"]
                start = time.monotonic()
                if frequency == 0:
                    if hasattr(self.audio, "stop"):self.audio.stop()
                elif continuous:
                    self.audio.start(frequency)
                else:
                    # Finite playback replaces the prior loop inside the audio backend.
                    self.audio.play(frequency, params["RunningTime"], self.abort_output)
                with self.lock:
                    self.buzzer_output = dict(params) if continuous else None
                if not continuous:
                    remaining = duration - (time.monotonic() - start)
                    if self.abort_output.wait(max(0, remaining)):
                        raise CommandError("DEVICE_ERROR", "Server stopped before completion.")
                with self.lock:
                    self.status["BuzzerFrequency"] = frequency
                    self.status["BuzzerRunningTime"] = params["RunningTime"]
                    self.status["BuzzerContinuous"] = continuous
            elif method == "SetuHandLED":
                if self.stopping.is_set():
                    raise CommandError("DEVICE_ERROR", "Server is stopping.")
                with self.lock:
                    self.status["LED"] = [params[name] for name in ("Red", "Green", "Blue")]
                    self.status["LEDBrightness"] = params["Brightness"]
        except CommandError as exc:
            error = exc
        except Exception as exc:
            error = CommandError("DEVICE_ERROR", f"Virtual output failed: {exc}")
        finally:
            with self.lock:
                if error:
                    # A failed transition must not leave a live interpolation behind.
                    self.display = self._display_at(time.monotonic())
                    self.motion = None
                self.busy = False
                self.output_done.set()
                self.active = None
                self.active_params = None
                if not self.powered_off:
                    self.log(f"{method} 완료" if error is None else f"{error.code} · {error.message}",
                             "info" if error is None else "error")
            connection.send(rid, error=error)

    def _home_outputs(self):
        if self.lifecycle.phase == "startup" and hasattr(self.audio, "enable_idle_output"):
            self.audio.enable_idle_output()
        elif hasattr(self.audio, "stop"):
            self.audio.stop()
        self._notice_note_index = 0 if hasattr(self.audio, "play_notice_note") else None
        with self.lock:
            now = time.monotonic()
            self.motion = (self._display_at(now), [1500] * 6, now, HOME_MS / 1000)
            self.status.update(LED=[0] * 3, LEDBrightness=100)
            self.buzzer_output = None

    def _home_complete(self):
        self.display = [1500.0] * 6
        self.motion = None

    def _notice_tone(self, hz, ms, cancel):
        with self.lock:
            if cancel.is_set():
                return
            notes = MELODIES[self.lifecycle.phase]
            self.buzzer_output = {"Frequency": hz, "RunningTime": ms, "Continuous": False}
        try:
            if self._notice_note_index is None:
                self.audio.play(hz, ms, cancel)
            else:
                self.audio.play_notice_note(self._notice_note_index, notes, ms, GAP_MS, cancel)
                self._notice_note_index += 1
        finally:
            with self.lock:
                self.buzzer_output = None

    def _display_at(self, now):
        if self.motion is None:
            return list(self.display)
        return interpolate_pose(self.motion, now)

    def snapshot(self):
        with self.lock:
            return {
                "status": copy.deepcopy(self.status), "pulses": self._display_at(time.monotonic()),
                "active": self.active, "params": copy.deepcopy(self.active_params),
                "buzzer_output": copy.deepcopy(self.buzzer_output),
                "phase": self.lifecycle.phase, "init_error": self.lifecycle.error,
                "connected": self.owner is not None and self.owner.admitted, "listening": self.listening,
                "powered_off": self.powered_off,
                "has_connections": bool(self.connections),
                "last_error_id": self.last_error_id,
                "events": list(self.events), "last_error": self.last_error, "busy": self.busy or bool(self.lifecycle.phase),
            }

    def drain(self):
        """Stop accepting/reading commands; preserve an already running output."""
        with self.lock:
            self.listening = False
            self.lifecycle.cancel()
            listener = self.listener
            connections = list(self.connections)
        if listener:
            listener.close()
        for connection in connections:
            connection.close()

    def shutdown(self):
        """Process shutdown, not a public robot Stop API."""
        self.drain()
        self.stopping.set()
        self.abort_output.set()
        if self.accept_thread:
            self.accept_thread.join(1)
        with self.lock:
            threads = list(self.threads)
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(3)
        if hasattr(self.audio, "close"):self.audio.close()
        elif hasattr(self.audio, "stop"):self.audio.stop()
        with self.lock:self.buzzer_output = None
