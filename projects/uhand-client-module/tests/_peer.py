"""Independent test-only TCP peer, not uHandVirtualServer or a device driver."""
import copy
import json
import socket
import threading

EMPTY = {
    "TargetPulses": None, "PulseRunningTime": None, "BuzzerFrequency": None,
    "BuzzerRunningTime": None, "BuzzerContinuous": None, "LED": None, "LEDBrightness": None,
}
PULSES = [f"Finger{i}Pulse" for i in range(1, 6)] + ["WristPulse"]


def reply(request, result=None, error=None):
    value = {"version": 2, "request_id": request["request_id"], "ok": error is None}
    value["result" if error is None else "error"] = result if error is None else error
    return value


def encoded(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


class Channel:
    def __init__(self, sock):
        self.sock = sock
        self.lock = threading.Lock()

    def raw(self, data):
        with self.lock:
            try:
                self.sock.sendall(data)
            except OSError:
                pass

    def send(self, value):
        self.raw(encoded(value))

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class Peer:
    def __init__(self, handler=None):
        self.handler = handler
        self.stop = threading.Event()
        self.started = threading.Event()
        self.owner_released = threading.Event()
        self.state_lock = threading.Lock()
        self.status = copy.deepcopy(EMPTY)
        self.busy = False
        self.owner = None
        self.requests = []
        self.channels = []
        self.workers = []
        self.errors = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def spawn(self, function):
        def checked():
            try:
                function()
            except Exception as exc:
                self.errors.append(exc)
        thread = threading.Thread(target=checked, daemon=True)
        self.workers.append(thread)
        thread.start()
        return thread

    def _accept(self):
        while not self.stop.is_set():
            try:
                sock, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            sock.settimeout(0.1)
            channel = Channel(sock)
            self.channels.append(channel)
            self.spawn(lambda c=channel: self._read(c))

    def _read(self, channel):
        buffer = b""
        try:
            while not self.stop.is_set():
                try:
                    data = channel.sock.recv(8192)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    req = json.loads(line)
                    self.requests.append(req)
                    if self.handler is None:
                        self.default(channel, req)
                    else:
                        self.handler(self, channel, req)
        finally:
            with self.state_lock:
                if self.owner is channel:
                    self.owner = None
                    self.owner_released.set()
            channel.close()

    def default(self, channel, req):
        method, params = req["method"], req["params"]
        if method == "Hello":
            with self.state_lock:
                if self.owner is not None:
                    channel.send(reply(req, error={"code": "BUSY", "message": "Another client owns the server."}))
                else:
                    self.owner = channel
                    self.owner_released.clear()
                    channel.send(reply(req))
            return
        if method == "GetStatus":
            with self.state_lock:
                value = copy.deepcopy(self.status)
            channel.send(reply(req, value))
            return
        with self.state_lock:
            if self.busy:
                channel.send(reply(req, error={"code": "BUSY", "message": "Output already running."}))
                return
            self.busy = True
        self.started.set()

        def finish():
            if self.stop.wait(params.get("RunningTime", 0) / 1000):
                return
            with self.state_lock:
                if method == "SetuHandPulse":
                    self.status["TargetPulses"] = [params[name] for name in PULSES]
                    self.status["PulseRunningTime"] = params["RunningTime"]
                elif method == "SetuHandBuzzer":
                    self.status["BuzzerFrequency"] = params["Frequency"]
                    self.status["BuzzerRunningTime"] = params["RunningTime"]
                    self.status["BuzzerContinuous"] = params.get("Continuous", False)
                elif method == "SetuHandLED":
                    if "RedEnable" in params:
                        self.status["LED"] = [255 * params[n] for n in ("RedEnable","GreenEnable","BlueEnable")]
                    else:
                        self.status["LED"] = [params[n] for n in ("Red","Green","Blue")]
                    self.status["LEDBrightness"] = params.get("Brightness", 100)
                self.busy = False
            channel.send(reply(req))
        self.spawn(finish)

    def close(self):
        self.stop.set()
        self.listener.close()
        self.thread.join(1)
        for channel in self.channels:
            channel.close()
        for worker in self.workers:
            worker.join(1)
        if self.errors:
            raise AssertionError(f"Test peer errors: {self.errors}")


class Call:
    def __init__(self, function):
        self.value = None
        self.error = None
        self.done = threading.Event()

        def run():
            try:
                self.value = function()
            except Exception as exc:
                self.error = exc
            finally:
                self.done.set()
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def result(self, timeout=3):
        if not self.done.wait(timeout):
            raise AssertionError("Test caller did not terminate.")
        if self.error:
            raise self.error
        return self.value
