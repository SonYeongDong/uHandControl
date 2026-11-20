"""File actions and transactional editor integration."""
from dataclasses import replace
from pathlib import Path
from copy import deepcopy
import re
from .shortcuts import PREFIX
from PySide6.QtCore import Qt, QTimer, QStandardPaths
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMessageBox
from .document import DocumentState
from .sequence_file import DEFAULT_SUFFIX, SUPPORTED_SUFFIXES, SequenceFile, read_file, write_file
from .motion import Motion, kind

FILTER = "uHand 동작 시퀀스 (" + " ".join("*" + suffix for suffix in SUPPORTED_SUFFIXES) + ")"

class FileUi:
    def init_document(self):
        self.document = DocumentState()
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        self.sequence_directory = Path(documents) / "uHandControl" / "sequences"

    def build_file_menu(self):
        menu = self.menuBar().addMenu("파일")
        self.save_feedback_timer = QTimer(self.file_save_button)
        self.save_feedback_timer.setSingleShot(True)
        self.save_feedback_timer.timeout.connect(lambda: self.file_save_button.setDown(False))
        self.file_actions = []
        for name, shortcut, callback in (
            ("새 파일", QKeySequence.StandardKey.New, self.new_document),
            ("열기…", QKeySequence.StandardKey.Open, self.open_document),
            ("저장", QKeySequence.StandardKey.Save, self.activate_save_action),
            ("다른 이름으로 저장…", QKeySequence.StandardKey.SaveAs, lambda: self.save_document(save_as=True)),
        ):
            action = QAction(name, self)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda checked=False, cb=callback: cb())
            menu.addAction(action)
            self.file_actions.append(action)
        menu.ensurePolished()
        # Leave a visible gutter between the longest label and its shortcut.
        menu.setMinimumWidth(menu.sizeHint().width() + 3 * menu.fontMetrics().height())
        self.file_open_button.setToolTip(f"동작 시퀀스 열기 ({PREFIX}O)")
        self.file_save_button.setToolTip(f"동작 시퀀스 저장 ({PREFIX}S)")

    def activate_save_action(self):
        if not self.files_available():
            return
        # Reuse the mouse-pressed style without emitting a second click.
        self.file_save_button.setDown(True)
        self.file_save_button.repaint()
        self.save_feedback_timer.start(300)
        self.save_document()

    def files_available(self):
        return not self.is_running() and not self.remote.busy and not self.remote_disconnect_pending

    def refresh_file_state(self):
        if not hasattr(self, "file_actions"):
            return
        available = self.files_available()
        for action in self.file_actions:
            action.setEnabled(available)
        self.file_open_button.setEnabled(available)
        self.file_save_button.setEnabled(available)
        dirty = self.document.dirty(self.sequence.items) or (not self.is_running() and self.changed())
        name = self.document.path.name if self.document.path else "새 동작 시퀀스"
        self.setWindowTitle(name + (" *" if dirty else "") + " — uHandMotionCreator")
        self.document_label.setText(("미저장 · " if dirty else "") + name)
        self.document_label.setToolTip(str(self.document.path) if self.document.path else "아직 파일로 저장하지 않았습니다.")

    def file_error(self, message):
        QMessageBox.warning(self, "시퀀스 파일", str(message))

    def file_choice(self, purpose, draft):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("동작 시퀀스 저장")
        if purpose == "save":
            dialog.setText("목록에 적용하지 않은 입력이 있습니다. 어떻게 저장할까요?")
            choices = (("apply", "입력 적용/추가 후 저장"), ("list", "목록만 저장"), ("cancel", "취소"))
        else:
            dialog.setText("저장하지 않은 작업이 있습니다. 계속하기 전에 저장할까요?")
            choices = ((("apply" if draft else "save"), ("입력 적용/추가 후 저장" if draft else "저장")),
                       ("discard", "모두 버리고 계속"), ("cancel", "취소"))
        buttons = {}
        for key, text in choices:
            buttons[dialog.addButton(text, QMessageBox.ButtonRole.RejectRole if key == "cancel" else QMessageBox.ButtonRole.ActionRole)] = key
        cancel = next(button for button, key in buttons.items() if key == "cancel")
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        return buttons.get(dialog.clickedButton(), "cancel")

    def choose_save_path(self):
        folder = self.document.path.parent if self.document.path else self.sequence_directory
        folder.mkdir(parents=True, exist_ok=True)
        current = self.document.path
        stem = current.stem if current else "동작 시퀀스"
        if current and current.name.lower().endswith(".uhand.json"):
            stem = current.name[:-len(".uhand.json")]
        initial = folder / (stem + DEFAULT_SUFFIX)
        path, _ = QFileDialog.getSaveFileName(self, "동작 시퀀스 저장", str(initial), FILTER,
                                             options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return None
        if not Path(path).suffix and not Path(path).name.endswith("."):
            path += DEFAULT_SUFFIX
        # Confirm the final path once, including when the suffix was added here.
        if Path(path).is_file() and QMessageBox.question(
                self, "덮어쓰기", f"{Path(path).name} 파일을 덮어쓸까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return None
        return Path(path)

    def save_document(self, save_as=False, draft_choice=None, closing=False):
        if not closing and not self.files_available():
            return False
        try:
            choice = draft_choice or (self.file_choice("save", True) if self.changed() else "list")
            if choice == "cancel":
                return False
            cards = list(self.sequence.items)
            serials = list(self.name_serials)
            selected = self.selected
            if choice == "apply":
                draft = self.draft()
                index = kind(draft)
                if 0 <= selected < len(cards) and kind(cards[selected]) == index:
                    cards[selected] = draft
                else:
                    self.sequence.require_space(1)
                    prefix = ("동작", "부저", "LED")[index]
                    if re.fullmatch(re.escape(prefix) + r" [0-9]+", draft.name):
                        draft = replace(draft, name=f"{prefix} {serials[index]:02d}")
                    selected = self.selected + 1 if 0 <= self.selected < len(cards) else len(cards)
                    cards.insert(selected, draft)
                    serials[index] += 1
            path = self.choose_save_path() if save_as or self.document.path is None else self.document.path
            if path is None:
                return False
            payload = SequenceFile(tuple(cards), tuple(serials), self.document.extensions)
            write_file(path, payload)
        except (OSError, ValueError) as exc:
            self.file_error(exc)
            return False
        # The file is durable before any editor state changes.
        if choice == "apply":
            inserted = len(cards) > len(self.sequence.items)
            self.sequence.commit(cards)
            self.name_serials = serials
            if inserted:
                self.show_inserted_cards((selected,))
            else:
                self.update_card_item(self.list.item(selected), selected)
                self.load_motion(self.sequence.items[selected])
                self.refresh_actions()
        self.document.mark_saved(path, cards)
        self.refresh_file_state()
        self.notice.setText("목록만 저장했습니다. 미적용 입력은 남아 있습니다." if self.changed() else "동작 시퀀스를 저장했습니다.")
        return True

    def protect_document(self, closing=False):
        draft = not self.is_running() and self.changed()
        if not draft and not self.document.dirty(self.sequence.items):
            return True
        choice = self.file_choice("replace", draft)
        if choice == "discard":
            return True
        if choice == "cancel":
            return False
        return self.save_document(draft_choice="apply" if draft else "list", closing=closing)

    def install_document(self, payload, path):
        self.stop_sound()
        self.document.extensions = deepcopy(payload.extensions or {})
        self.sequence.items = tuple(payload.cards)
        self.sequence.undo_stack.clear()
        self.sequence.redo_stack.clear()
        self.name_serials = list(payload.serials)
        self.document.mark_saved(path, payload.cards)
        self.repeat_playback.setChecked(False)
        if self.server_panel is not None:
            self.server_panel.repeat.setChecked(False)
        self.refresh_list(0 if payload.cards else -1)
        if not payload.cards:
            self.load_motion(Motion(name="동작 01"))
        self.refresh_file_state()
        self.list.horizontalScrollBar().setValue(0)
        self.sync_sequence_window()
        if self.sequence_window is not None:
            self.sequence_window.list.verticalScrollBar().setValue(0)
        QTimer.singleShot(0, lambda: self.list.horizontalScrollBar().setValue(0))

    def new_document(self):
        if self.files_available() and self.protect_document():
            self.install_document(SequenceFile(), None)
            return True
        return False

    def open_document(self):
        if not self.files_available():
            return False
        folder = self.document.path.parent if self.document.path else self.sequence_directory
        path, _ = QFileDialog.getOpenFileName(self, "동작 시퀀스 열기", str(folder), FILTER)
        if not path:
            return False
        try:
            payload = read_file(path)
        except (OSError, ValueError) as exc:
            self.file_error(exc)
            return False
        if not self.protect_document():
            return False
        self.install_document(payload, Path(path))
        return True
