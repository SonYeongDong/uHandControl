"""Threaded single-owner server, independent of GUI and physical hardware."""
from collections import deque
from pathlib import Path
import copy
import socket
import threading
import time

from uhand_server_lifecycle import HOME_MS, Lifecycle

from uhand_server_lifecycle import status_reply, led_output

from .protocol import (
    CommandError, EMPTY_STATUS, MAX_FRAME, PULSE_NAMES,
    decode, response, validate_bind, validate_request,
)


LINK_CHECK_INTERVAL = 0.2


def read_link(directory):
    """A down counter also catches an unplug/replug between successive reads."""
    def read(name):
        try:
            return int((directory / name).read_text().strip())
        except (OSError, ValueError):
            return None
    return read("carrier_down_count"), read("carrier")


def configure_peer_socket(sock, log):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    # Keepalive covers idle peers. USER_TIMEOUT also bounds outstanding replies.
    for name, value in (("TCP_KEEPIDLE", 1), ("TCP_KEEPINTVL", 1),
                        ("TCP_KEEPCNT", 3), ("TCP_USER_TIMEOUT", 3000)):
        option = getattr(socket, name, None)
        if option is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, option, value)
            except OSError as exc:
                log(f"Could not set {name}: {exc}", "warning")


class Connection:
    def __init__(self, server, sock, address):
        self.server, self.sock, self.address = server, sock, address
        self.send_lock = threading.Lock()
        self.closed = threading.Event()
        self.seen = set()
        self.admitted = False
        self.link_directory = server.link_directory
        self.down_count = None
        self.next_link_check = 0
        if self.link_directory is not None:
            self.down_count, _ = read_link(self.link_directory)

    def link_lost(self, now):
        if self.link_directory is None or now < self.next_link_check:
            return False
        self.next_link_check = now + LINK_CHECK_INTERVAL
        count, carrier = read_link(self.link_directory)
        changed = self.down_count is not None and count is not None and count != self.down_count
        if count is not None:
            self.down_count = count
        return carrier == 0 or changed

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
                now = time.monotonic()
                if self.link_lost(now):
                    self.server.log("Ethernet link lost; closing Client session.")
                    break
                if not self.admitted and now > hello_deadline:
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


class PhysicalServer:
    def __init__(self, backend, host="127.0.0.1", port=5000, logger=None, link_directory=None):
        self.address=validate_bind(host,port)
        self.host,self.port=str(self.address),port
        self.backend=backend
        self.logger=logger
        self.link_directory = Path(link_directory) if link_directory is not None else None
        self.lock=threading.RLock()
        self.stopping=threading.Event()
        self.abort_output=threading.Event()
        self.output_done=threading.Event();self.output_done.set()
        self.owner=None;self.connections=set();self.threads=set()
        self.listener=None;self.accept_thread=None;self.listening=False
        self.status=copy.deepcopy(EMPTY_STATUS)
        self.lifecycle = Lifecycle(self)
        self.busy=False
        self.buzzer_continuous=False
        self.events=deque(maxlen=200)
    def log(self,message,level="info"):
        with self.lock:self.events.append((time.time(),level,message))
        if self.logger:
            try:self.logger(level,message)
            except Exception:pass  # A failed log sink must not interrupt control or replies.
    def start(self):
        with self.lock:
            if self.listener is not None or self.stopping.is_set():raise RuntimeError("Create a new server to restart.")
            sock=socket.socket(socket.AF_INET if self.address.version==4 else socket.AF_INET6,socket.SOCK_STREAM)
            try:
                if hasattr(socket,"SO_EXCLUSIVEADDRUSE"):sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                sock.bind((self.host,self.port));sock.listen(8);sock.settimeout(.2)
            except BaseException:sock.close();raise
            self.listener=sock;self.port=sock.getsockname()[1];self.listening=True
            ready = self.lifecycle.begin("startup")
        self.accept_thread=threading.Thread(target=self._accept,daemon=True);self.accept_thread.start()
        ready.wait()
        if self.lifecycle.error:
            raise RuntimeError(self.lifecycle.error)
        self.log(f"Listening on {self.host}:{self.port}")
    def _accept(self):
        while self.listening and not self.stopping.is_set():
            try:
                sock, address = self.listener.accept()
            except socket.timeout:continue
            except OSError as exc:
                if not self.listening or self.stopping.is_set():
                    return
                self.log(f"Accept failed: {exc}", "warning")
                self.stopping.wait(LINK_CHECK_INTERVAL)
                continue
            try:
                sock.settimeout(LINK_CHECK_INTERVAL)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                configure_peer_socket(sock, self.log)
            except OSError as exc:
                self.log(f"Client socket setup failed: {exc}", "warning")
                sock.close()
                continue
            connection=Connection(self,sock,address)
            with self.lock:
                if not self.listening or len(self.connections)>=16:connection.close();continue
                self.connections.add(connection)
            self._spawn(connection.run)
    def _spawn(self,function,name=None):
        def run():
            try:function()
            finally:
                with self.lock:self.threads.discard(threading.current_thread())
        thread=threading.Thread(target=run,name=name,daemon=True)
        with self.lock:self.threads.add(thread)
        thread.start()
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

    def dispatch(self,connection,rid,method,params):
        with self.lock:
            if not self.listening:raise CommandError("BUSY","Server is draining.")
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
            if self.owner is not connection:raise CommandError("INVALID_ARGUMENT","Send Hello first.")
            if method=="GetStatus":result = status_reply(copy.deepcopy(self.status), params)
            else:
                if self.busy:raise CommandError("BUSY","An output is already running.")
                self.busy=True;self.output_done.clear()
                self._spawn(lambda:self._execute(connection,rid,method,params));return
        connection.send(rid,result)
    def _execute(self,connection,rid,method,params):
        error=None
        try:
            self.log(f"{method} started")
            if method=="SetuHandPulse":
                pulses=[params[name] for name in PULSE_NAMES]
                self.backend.set_pulses(pulses,params["RunningTime"])
                if self.abort_output.wait(params["RunningTime"]/1000):raise RuntimeError("Forced shutdown before completion.")
                update={"TargetPulses":pulses,"PulseRunningTime":params["RunningTime"]}
            elif method=="SetuHandBuzzer":
                frequency=params["Frequency"];continuous=params["Continuous"]
                if frequency == 0:
                    self.backend.silence_buzzer()
                elif continuous:
                    self.backend.start_buzzer(frequency)
                else:
                    self.backend.set_buzzer(frequency,params["RunningTime"])
                self.buzzer_continuous=continuous and frequency > 0
                if not continuous:
                    try:
                        if self.abort_output.wait(params["RunningTime"]/1000):raise RuntimeError("Forced shutdown before completion.")
                    finally:
                        if frequency > 0:self.backend.finish_buzzer(frequency)
                update={"BuzzerFrequency":frequency,"BuzzerRunningTime":params["RunningTime"],"BuzzerContinuous":continuous}
            else:
                rgb = [params[name] for name in ("Red", "Green", "Blue")]
                brightness = params["Brightness"]
                self.backend.set_led(led_output(rgb, brightness))
                update = {"LED": rgb, "LEDBrightness": brightness}
            with self.lock:self.status.update(update)
        except CommandError as exc:error=exc
        except Exception as exc:error=CommandError("DEVICE_ERROR",f"Hardware output failed: {exc}")
        finally:
            with self.lock:
                self.busy=False
                self.output_done.set()
            self.log(f"{method} completed" if error is None else f"{error.code}: {error.message}", "info" if error is None else "error")
            connection.send(rid,error=error)
    def _home_outputs(self):
        self.backend.silence_buzzer()
        self.buzzer_continuous = False
        self.backend.set_led([False] * 3)
        self.backend.set_pulses([1500] * 6, HOME_MS)

    def _home_complete(self):
        pass  # No joint-position feedback from the physical device.

    def _notice_tone(self, hz, ms, cancel):
        try:
            self.backend.set_buzzer(hz, ms)
            cancel.wait(ms / 1000)
        finally:
            self.backend.finish_buzzer(hz)

    def snapshot(self):
        with self.lock:return {"status":copy.deepcopy(self.status),"busy":self.busy or bool(self.lifecycle.phase),"phase":self.lifecycle.phase,"events":list(self.events)}
    def drain(self):
        with self.lock:
            self.listening=False
            self.lifecycle.cancel()
            if self.listener:self.listener.close()
            connections=list(self.connections)
        for connection in connections:connection.close()
    def shutdown(self,timeout=23):
        self.drain()
        completed=self.output_done.wait(timeout)
        if not completed:
            self.abort_output.set()
            if not self.output_done.wait(2):
                raise RuntimeError("Backend did not return; hardware ownership retained until process exit.")
        self.stopping.set()
        if self.accept_thread:self.accept_thread.join(1)
        with self.lock:threads=list(self.threads)
        for thread in threads:
            if thread is not threading.current_thread():thread.join(1)
        if self.buzzer_continuous:
            self.backend.silence_buzzer()
            self.buzzer_continuous=False
        self.backend.close()
        return completed
