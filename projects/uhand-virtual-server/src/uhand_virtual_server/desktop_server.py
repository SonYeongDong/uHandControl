"""Run the network controller independently of the desktop render loop."""
import multiprocessing
import time

from .server import VirtualServer, interpolate_pose


def _serve(pipe, host, port):
    server = None
    try:
        try:
            server = VirtualServer(host, port)
        except Exception as exc:
            pipe.send((False, ("RuntimeError", str(exc))))
            return
        pipe.send((True, server.snapshot()))
        while True:
            action, args, kwargs = pipe.recv()
            if action == "shutdown":
                break
            try:
                if action == "start":
                    server.start(*args, **kwargs)
                    result = server.host, server.port
                elif action == "snapshot":
                    with server.lock:
                        result = server.snapshot()
                        result["motion"] = server.motion
                elif action == "stop_listening":
                    result = server.stop_listening()
                elif action == "drain":
                    result = server.drain()
                elif action == "log":
                    result = server.log(*args)
                elif action == "clear_events":
                    result = server.clear_events()
                else:
                    raise ValueError(f"Unknown desktop request: {action}")
            except (OSError, RuntimeError, ValueError) as exc:
                kind = "OSError" if isinstance(exc, OSError) else type(exc).__name__
                pipe.send((False, (kind, str(exc))))
            else:
                pipe.send((True, result))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        if server is not None:
            server.shutdown()
        pipe.close()


class DesktopServer:
    """GUI-thread interface. All networking, timed outputs and audio live in the child."""
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.listening = False
        self._process = None
        self._pipe = None
        self._state = {}
        self._launch()

    def _launch(self):
        ctx = multiprocessing.get_context("spawn")
        self._pipe, child = ctx.Pipe()
        self._process = ctx.Process(target=_serve, args=(child, self.host, self.port),
                                    name="uHandVirtualServer-control", daemon=True)
        try:
            self._process.start()
        finally:
            child.close()
        try:
            self._state = self._receive()
        except Exception:
            self.shutdown()
            raise

    def _receive(self):
        if not self._pipe.poll(6):
            raise TimeoutError("가상 서버 프로세스 응답 시간 초과")
        ok, result = self._pipe.recv()
        if not ok:
            kind, message = result
            raise {"OSError": OSError, "ValueError": ValueError}.get(kind, RuntimeError)(message)
        return result

    def _request(self, action, *args, **kwargs):
        self._pipe.send((action, args, kwargs))
        return self._receive()

    def start(self, host=None, port=None, *, background=False):
        if self._process is None:
            self._launch()
        self.host, self.port = self._request("start", host, port, background=background)
        self.listening = True

    def stop_listening(self):
        self._request("stop_listening")
        self.listening = False

    def drain(self):
        self._request("drain")
        self.listening = False

    def clear_events(self):
        if self._process is None:
            self._state["events"] = []
            return 0
        return self._request("clear_events")

    def log(self, message, level="info"):
        if self._process is None:
            self._state["last_error"] = message
            self._state["last_error_id"] += 1
        else:
            self._request("log", message, level)

    def snapshot(self):
        if self._process is not None:
            try:
                self._state = self._request("snapshot")
            except (EOFError, OSError):
                self.shutdown()
                self._state.update(listening=False, connected=False, busy=False, active=None,
                                   phase=None, powered_off=True, has_connections=False,
                                   motion=None, buzzer_output=None)
                self.log("가상 서버 프로세스 연결이 끊어졌습니다.", "error")
        state = self._state.copy()
        if state.get("motion"):
            state["pulses"] = interpolate_pose(state["motion"], time.monotonic())
        return state

    def shutdown(self):
        if self._process is None:
            return
        try:
            self._pipe.send(("shutdown", (), {}))
        except (OSError, EOFError):
            pass
        finally:
            self._pipe.close()
            self._process.join(5)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join()
            self._process.close()
            self._process = None
            self.listening = False
