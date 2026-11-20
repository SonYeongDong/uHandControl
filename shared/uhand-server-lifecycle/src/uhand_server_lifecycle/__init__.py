"""Readiness sequences shared by the physical and virtual uHand servers."""
import socket
import threading


MELODIES = {
    "startup": (523, 659, 784),
    "connect": (659, 880),
    "disconnect": (440, 370, 294),
}
LABELS = {"startup": "서버 준비", "connect": "Client 연결", "disconnect": "Client 연결 해제"}
HOME_MS = 500
TONE_MS = 175
GAP_MS = 75


def reset_status():
    return dict(TargetPulses=[1500] * 6, PulseRunningTime=HOME_MS,
                BuzzerFrequency=0, BuzzerRunningTime=100, BuzzerContinuous=False, LED=[0] * 3, LEDBrightness=100)


def led_output(rgb, brightness):
    return [(channel * brightness + 50) // 100 for channel in rgb]


def status_reply(status, params):
    """status is a snapshot; original v2 readers expect six fields and boolean lamps."""
    if not params.get("IncludeLEDBrightness"):
        brightness = status.pop("LEDBrightness")
        if status["LED"] is not None:
            status["LED"] = [bool(v) for v in led_output(status["LED"], brightness)]
    return status


def enable_keepalive(sock):
    """Let TCP detect an idle peer that disappeared without sending FIN."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    for name, value in (("TCP_KEEPIDLE", 10), ("TCP_KEEPINTVL", 3), ("TCP_KEEPCNT", 3)):
        option = getattr(socket, name, None)
        if option is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, option, value)
            except OSError:
                pass  # SO_KEEPALIVE still uses the platform's default timing.


class Lifecycle:
    """begin/cancel are called with the server lock held. Device I/O runs outside it."""
    def __init__(self, server):
        self.server = server
        self.phase = None
        self.error = None
        self.cancelled = threading.Event()
        self.serial = threading.Lock()

    def cancel(self):
        self.cancelled.set()

    def begin(self, phase, owner=None, request_id=None):
        self.cancel()
        cancel = self.cancelled = threading.Event()
        self.phase = phase
        self.error = None
        done = threading.Event()
        self.server.log(f"{LABELS[phase]} · 초기화 시작")
        self.server._spawn(lambda: self._run(phase, owner, request_id, cancel, done), "uhand-lifecycle")
        return done

    def _run(self, phase, owner, request_id, cancel, done):
        server = self.server
        try:
            with self.serial:
                server.output_done.wait()
                if cancel.is_set():
                    return
                server._home_outputs()
                if cancel.wait(HOME_MS / 1000):
                    return
                with server.lock:
                    server.status.update(reset_status())
                    server._home_complete()
                for index, hz in enumerate(MELODIES[phase]):
                    if index and cancel.wait(GAP_MS / 1000):
                        return
                    if cancel.is_set():
                        return
                    server.log(f"{LABELS[phase]} · {hz} Hz")
                    server._notice_tone(hz, TONE_MS, cancel)
                with server.lock:
                    if cancel.is_set():
                        return
                    self.phase = None
                    server.abort_output.clear()
                    server.log(f"{LABELS[phase]} · 완료")
                    if owner is not None:
                        owner.admitted = True
                        owner.send(request_id)
        except Exception as exc:
            with server.lock:
                if not cancel.is_set():
                    self.error = f"{LABELS[phase]} 실패 · {exc}"
                    self.phase = None
                    server.log(self.error, "error")
                    if owner is not None:
                        server.owner = None
                        owner.send(request_id, error=server._device_error(self.error))
                        owner.close()
        finally:
            with server.lock:
                if self.cancelled is cancel and cancel.is_set():
                    self.phase = None
            done.set()
