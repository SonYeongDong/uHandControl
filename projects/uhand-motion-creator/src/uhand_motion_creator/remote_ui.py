"""Main-window coordination for optional remote control."""
from time import perf_counter
from PySide6.QtCore import QTimer, QSignalBlocker, Qt
from .remote import RemoteSession
from .remote_panel import ServerPanel
from .motion import Motion, Buzzer, LED, call_code


class RemoteUi:
    def init_remote(self):
        self.remote = RemoteSession()
        self.remote_running = False
        self.remote_endpoint = ""
        self.remote_disconnect_pending = False
        self.remote_close_pending = False
        self.server_panel = None
        self.remote_last_query = perf_counter()
        self.remote_timer = QTimer(self)
        self.remote_timer.setInterval(40)
        self.remote_timer.timeout.connect(self.poll_remote)

    def is_running(self):
        return self.playback is not None or self.remote_running

    def sequence_locked(self):
        return self.is_running() or self.live.active

    def show_server_panel(self):
        if self.server_panel is None:self.server_panel = ServerPanel(self)
        self.server_panel.refresh()
        self.server_panel.show();self.server_panel.raise_();self.server_panel.activateWindow()

    def remote_draft(self):
        if self.tabs.currentIndex() == 1:
            return Buzzer(self.frequency.value(), self.buzzer_time.value(), "직접 제어", self.continuous.isChecked())
        if self.tabs.currentIndex() == 2:
            return self.led_editor.card("직접 제어")
        return Motion(tuple(s.value() for s in self.spins), self.time.value(), "직접 제어")

    def valid_remote_draft(self):
        try:self.remote_draft();return True
        except ValueError:return False

    def refresh_remote_controls(self, *_):
        self.refresh_file_state()
        if not hasattr(self, "remote_apply_button"):return
        self.live.refresh()
        ready = self.remote.connected and not self.remote.busy and not self.sequence_locked() and not self.live.pending and not self.remote_disconnect_pending
        direct = self.server_panel is not None and self.server_panel.direct.isChecked()
        self.remote_apply_button.setEnabled(ready and direct and self.valid_remote_draft())
        self.remote_mute_button.setEnabled(ready)
        self.remote_led_off_button.setEnabled(ready)
        self.remote_apply_button.setToolTip("서버 연결·테스트 창에서 직접 제어 모드를 켜세요." if not direct else "현재 탭의 파라미터를 서버로 전송합니다.")
        self.connection_badge.setText(("SERVER · " + self.remote_endpoint) if self.remote.connected else "OFFLINE · 로컬 편집")
        if self.server_panel is not None:self.server_panel.refresh()

    def remote_message(self, value):
        if self.server_panel is not None:self.server_panel.progress.setText(value)
        self.connection_badge.setToolTip(value)

    def connect_remote(self):
        if self.remote.busy or self.is_running():return
        panel = self.server_panel
        self.remote_endpoint = f"{panel.ip.text().strip()}:{panel.port.value()}"
        self.submit_remote("connect", endpoint=(panel.ip.text().strip(), panel.port.value()))
        self.remote_message("연결 중 · " + self.remote_endpoint)

    def disconnect_remote(self):
        if not self.remote.connected and not self.remote.busy:return
        self.remote_disconnect_pending = True
        self.live.reset_session()
        if self.remote.busy:
            self.remote.stop()
            self.remote_message("현재 요청 완료 후 부저를 끄고 연결을 해제합니다.")
        else:
            self.submit_remote("disconnect")
        self.refresh_remote_controls()

    def query_remote(self):
        if self.remote.connected and not self.remote.busy and not self.is_running() and not self.remote_disconnect_pending:
            self.remote.query_status()
            self.remote_last_query = perf_counter()

    def apply_remote(self):
        if not self.remote_apply_button.isEnabled():return
        self.submit_remote("run", cards=((-1, self.remote_draft()),), cleanup=False)

    def mute_remote(self):
        if not self.remote_mute_button.isEnabled():return
        self.submit_remote("run", cards=((-1, Buzzer(0, 100, "소리 끄기", True)),), cleanup=False)

    def led_off_remote(self):
        if not self.remote_led_off_button.isEnabled():return
        self.submit_remote("run", cards=((-1, LED(name="LED 끄기")),), cleanup=False)

    def run_remote(self, scope):
        if not self.remote.connected or self.remote.busy or self.sequence_locked() or self.live.pending or not self.sequence.items:return
        if scope != "all" and (self.selected < 0 or not self.list.selected_rows()):return
        if not self.confirm_discard():return
        start = 0 if scope == "all" else self.selected
        end = start + 1 if scope == "selected" else len(self.sequence.items)
        self.submit_remote("run", cards=tuple(enumerate(self.sequence.items))[start:end], cleanup=True,
                           repeat=self.server_panel is not None and self.server_panel.repeat.isChecked())

    def submit_remote(self, operation, **kwargs):
        try:self.remote.submit(operation, **kwargs)
        except (RuntimeError, ValueError) as exc:self.remote_message(str(exc));return
        self.remote_last_query = perf_counter()
        if operation == "run":
            self.remote_running = True
            self.stop_sound()
            self.viewport.drag = None;self.viewport.previewing = True
            self.controls.setEnabled(False);self.list.setEnabled(False)
            # Saved cards use nonnegative indices; direct controls use -1.
            # Only sequence playback replaces the current preview with the hand.
            if any(index >= 0 for index, _ in kwargs.get("cards", ())):
                self.preview_stack.setCurrentIndex(0)
            self.remote_message("서버 실행 중 · " + self.remote_endpoint)
        self.refresh_actions()
        self.refresh_remote_controls()

    def stop_remote(self):
        if not self.remote_running:return
        self.remote.stop()
        message = "정지 요청 · 현재 명령 완료 후 다음 카드 실행 중단"
        self.remote_message(message);self.playback_status.setText(message)
        self.refresh_remote_controls()

    def show_remote_status(self, value):
        if value is not None and self.server_panel is not None:
            pulses = value["TargetPulses"]
            pulse_text = "미설정" if pulses is None else " / ".join(map(str, pulses))
            def ms(field):
                return "미설정" if value[field] is None else f"{value[field]} ms"
            frequency = value["BuzzerFrequency"]
            buzzer = "미설정" if frequency is None else f"{frequency} Hz" + (" · 무음" if frequency == 0 else "")
            continuous = value["BuzzerContinuous"]
            mode = "미설정" if continuous is None else ("연속 유지" if continuous else "지정 시간")
            rgb = value["LED"]
            led = "미설정" if rgb is None else f"RGB {rgb[0]}, {rgb[1]}, {rgb[2]} · 밝기 {value['LEDBrightness']}%"
            text = (
                f"손가락 1~5 / 손목: {pulse_text}\n"
                f"손동작 시간: {ms('PulseRunningTime')}\n"
                f"부저: {buzzer} · {mode}\n"
                f"부저 시간: {ms('BuzzerRunningTime')}\n"
                f"삼색 LED: {led}")
            if self.server_panel.status.toPlainText() != text:
                self.server_panel.status.setPlainText(text)

    def poll_remote(self):
        for event in self.remote.poll():
            if event["type"] == "poll_done":
                self.remote_last_query = perf_counter()
                if event["errors"]:
                    message = "서버 상태 조회 오류 · " + " / ".join(event["errors"])
                    if not event["connected"]:
                        message += " · 연결 종료: 장치 실행 상태를 확인할 수 없습니다."
                        if self.server_panel is not None:
                            self.server_panel.status.setPlainText("연결 종료 · 표시 상태 유효하지 않음")
                    self.remote_message(message)
                    self.refresh_actions();self.refresh_remote_controls()
                else:
                    self.show_remote_status(event["status"])
            elif event["type"] == "status":
                self.show_remote_status(event["value"])
            elif event["type"] == "progress":
                index = event["index"];motion = event["card"]
                if index >= 0:
                    if self.playing_row >= 0:self.list.item(self.playing_row).setData(Qt.ItemDataRole.UserRole+1, False)
                    self.playing_row = index
                    self.list.item(index).setData(Qt.ItemDataRole.UserRole+1, True)
                    with QSignalBlocker(self.list):self.list.setCurrentRow(index)
                    self.selected = index;self.load_motion(motion)
                    self.preview.setPlainText(call_code(motion))
                    self.list.scrollToItem(self.list.item(index))
                message = f"서버 실행 · {index+1}/{len(self.sequence.items)} · {motion.name}" if index >= 0 else "서버 직접 제어 중"
                if event.get("repeat"):
                    message = f"반복 {event['cycle']}회차 · " + message
                self.playback_status.setText(message);self.remote_message(message)
                self.schedule_sequence_sync()
            elif event["type"] == "done":
                if event["operation"] == "live":
                    self.live.completed(event)
                    if self.remote_disconnect_pending:
                        if self.remote.connected:
                            self.submit_remote("disconnect")
                        else:
                            self.remote_disconnect_pending = False
                    if not self.live.active or not self.remote.connected or self.remote_disconnect_pending:
                        self.refresh_actions()
                    continue
                if self.remote_running:
                    if self.playing_row >= 0:
                        self.list.item(self.playing_row).setData(Qt.ItemDataRole.UserRole+1, False)
                        self.load_motion(self.sequence.items[self.selected])
                    self.playing_row = -1;self.remote_running = False
                    self.viewport.previewing = False
                    self.preview_stack.setCurrentIndex(self.tabs.currentIndex())
                    self.controls.setEnabled(True);self.list.setEnabled(True);self.listen_button.setEnabled(True)
                    self.schedule_sequence_sync()
                self.show_remote_status(event["status"])
                if event["errors"]:
                    if self.remote_close_pending and event["operation"] in ("run", "disconnect"):
                        self.remote_close_pending = False
                        self.remote_disconnect_pending = False
                    message = "서버 오류 · " + " / ".join(event["errors"])
                    if not event["connected"]:
                        message += (" · 연결하지 못했습니다. 주소와 서버 상태를 확인하세요."
                                    if event["operation"] == "connect" else
                                    " · 연결 종료: 명령 실행·부저 종료 여부를 확인할 수 없습니다.")
                        if self.server_panel is not None:self.server_panel.status.setPlainText("연결 종료 · 표시 상태 유효하지 않음")
                    self.remote_message(message);self.playback_status.setText(message)
                elif event["operation"] != "status":
                    message = {"connect": "연결 완료 · 실행 버튼을 눌러 테스트하세요.",
                               "disconnect": "연결 해제 완료",
                               "run": "서버 실행 중단 완료" if event["stopped"] else "서버 실행 완료"}[event["operation"]]
                    self.remote_message(message)
                    if event["operation"] == "run":self.playback_status.setText(message)
                if not self.remote.connected:
                    self.remote_disconnect_pending = False
                    if self.server_panel is not None:
                        self.server_panel.direct.setChecked(False)
                        if not event["errors"]:self.server_panel.status.setPlainText("연결 안 됨 · 상태를 다시 조회하려면 연결하세요.")
                if self.remote_disconnect_pending and self.remote.connected:
                    self.submit_remote("disconnect")
                self.remote_last_query = perf_counter()
                self.refresh_actions();self.refresh_remote_controls()
        self.live.dispatch()
        if self.remote_close_pending and not self.remote.busy:
            if self.remote.connected:
                self.disconnect_remote()
            else:
                self.remote_close_pending = False
                self.force_close = True
                self.close()
                return
        if self.remote.connected and not self.remote.busy and not self.remote.status_busy and not self.is_running() and perf_counter()-self.remote_last_query >= 2:
            self.query_remote()

    def defer_remote_close(self):
        if not self.remote.busy and not self.remote.connected:return False
        self.remote_close_pending = True
        self.disconnect_remote()
        return True
