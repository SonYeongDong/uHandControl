"""Background execution through the public uHandClientModule API."""
from queue import Queue, Empty
from threading import Event, Thread
from time import monotonic
import uhand_client_module as hand
from .motion import Motion, Buzzer, LED


class RemoteSession:
    """One operation at a time; Qt consumes events without blocking its event loop."""
    def __init__(self, client=hand):
        self.client = client
        self.connected = False
        self.busy = False
        self.events = Queue()
        self.cancel = Event()
        self.thread = None
        self.status_busy = False
        self.generation = 0

    def submit(self, operation, *, endpoint=None, cards=(), cleanup=True, repeat=False):
        if self.busy:
            raise RuntimeError("서버 요청 처리 중입니다.")
        if operation not in ("connect", "disconnect", "status", "run", "live"):
            raise ValueError(operation)
        if operation != "connect" and not self.connected:
            raise RuntimeError("먼저 서버에 연결하세요.")
        if operation == "connect" and self.connected:
            raise RuntimeError("기존 연결을 해제하세요.")
        cards = tuple(cards)
        if operation in ("live", "run") and (not cards or any(type(c) not in (Motion, Buzzer, LED) for _, c in cards)):
            raise ValueError("실행할 카드가 없습니다.")
        if type(repeat) is not bool:
            raise ValueError("반복 재생 값은 bool이어야 합니다.")
        if repeat:
            if operation != "run" or not cleanup:
                raise ValueError("반복 재생은 저장 카드 실행에서만 지원합니다.")
            if not any(isinstance(c, Motion) or isinstance(c, Buzzer) and not c.continuous for _, c in cards):
                raise ValueError("즉시 적용 카드만으로는 반복할 수 없습니다. 손동작 또는 지정 시간 부저(0Hz 무음 포함) 카드를 추가하세요.")
        if operation in ("connect", "disconnect"):
            self.generation += 1
        self.busy = True
        self.cancel.clear()
        self.thread = Thread(target=self._work, args=(operation, endpoint, cards, cleanup, repeat),
                             name="Creator-server-request", daemon=True)
        self.thread.start()

    def query_status(self):
        """Read-only polling never occupies the output-command slot."""
        if not self.connected or self.status_busy:
            return
        self.status_busy = True
        generation = self.generation
        Thread(target=self._query_status, args=(generation,),
               name="Creator-status-poll", daemon=True).start()

    def _query_status(self, generation):
        status = None
        errors = []
        connected = True
        try:
            status = self.client.GetStatus()
        except Exception as exc:
            errors.append(str(exc))
            connected = isinstance(exc, (hand.RemoteError, hand.InputValidationError))
        self.events.put({"type": "poll_done", "generation": generation,
                         "status": status, "errors": errors, "connected": connected})

    def stop(self):
        self.cancel.set()

    def poll(self):
        result = []
        while True:
            try:
                event = self.events.get_nowait()
            except Empty:
                return result
            if event["type"] == "poll_done":
                self.status_busy = False
                # A response from an earlier connection must not change a new session.
                if event["generation"] != self.generation:
                    continue
                if not event["connected"]:
                    self.connected = False
                    self.generation += 1
            if event["type"] == "done":
                self.busy = False
                if event["generation"] != self.generation:
                    event["connected"] = False
                self.connected = event["connected"]
                if not self.connected:
                    self.generation += 1
            result.append(event)

    def _send_card(self, card):
        if isinstance(card, Motion):
            self.client.SetuHandPulse(*card.pulses, card.running_time)
        elif isinstance(card, Buzzer):
            self.client.SetuHandBuzzer(card.frequency, card.running_time, card.continuous)
        else:
            self.client.SetuHandLED(*card.rgb, card.brightness)

    def _work(self, operation, endpoint, cards, cleanup, repeat):
        connected = self.connected
        generation = self.generation
        errors = []
        status = None

        def failure(exc, prefix=""):
            nonlocal connected
            errors.append(prefix + str(exc))
            if not isinstance(exc, (hand.RemoteError, hand.InputValidationError)):
                connected = False
                self.client.Disconnect()

        def silence():
            try:
                self.client.SetuHandBuzzer(0, 100, True)
            except Exception as exc:
                failure(exc, "부저 종료 확인 실패: ")

        try:
            if operation == "connect":
                self.client.Connect(*endpoint)
                connected = True
            elif operation == "live":
                self._send_card(cards[0][1])
            elif operation == "run":
                cycle = 1
                while not self.cancel.is_set():
                    for index, card in cards:
                        if self.cancel.is_set():
                            break
                        self.events.put({"type": "progress", "index": index, "card": card, "cycle": cycle, "repeat": repeat})
                        self._send_card(card)
                        self.events.put({"type": "status", "value": self.client.GetStatus()})
                    if not repeat:
                        break
                    cycle += 1
        except Exception as exc:
            failure(exc)
        finally:
            if connected and (operation == "disconnect" or
                    operation == "run" and (cleanup or errors or self.cancel.is_set())):
                silence()
            if connected and operation not in ("disconnect", "live"):
                try:
                    status = self.client.GetStatus()
                except Exception as exc:
                    failure(exc)
            if operation == "disconnect" or operation == "connect" and errors:
                self.client.Disconnect()
                connected = False
            self.events.put({"type": "done", "operation": operation, "generation": generation, "finished_at": monotonic(), "connected": connected,
                             "errors": errors, "status": status, "stopped": self.cancel.is_set()})
