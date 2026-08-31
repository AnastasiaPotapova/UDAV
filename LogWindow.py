import os
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices, QTextCursor
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPlainTextEdit, QPushButton

from logger_setup import app_qt_handler, controller_qt_handler, APP_LOG_FILE, CONTROLLER_LOG_FILE

MAX_LINES = 100


class LogTab(QWidget):
    def __init__(self, log_file_path: str, qt_handler):
        super().__init__()
        self.log_file_path = log_file_path

        layout = QVBoxLayout(self)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()
        self.open_file_btn = QPushButton("Открыть полный файл лога")
        self.open_file_btn.clicked.connect(self.open_full_log)
        btn_layout.addWidget(self.open_file_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # живое обновление из логгера
        qt_handler.log_signal.connect(self.append_line)

        self._load_last_lines()

    def _load_last_lines(self):
        if not os.path.exists(self.log_file_path):
            return
        try:
            with open(self.log_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-MAX_LINES:]
            self.text_edit.setPlainText("".join(lines).rstrip("\n"))
            self._scroll_to_end()
        except Exception as e:
            self.text_edit.setPlainText(f"Ошибка чтения файла лога: {e}")

    def _scroll_to_end(self):
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.text_edit.setTextCursor(cursor)
        self.text_edit.ensureCursorVisible()

    def append_line(self, line: str):
        self.text_edit.appendPlainText(line)

        # держим не больше MAX_LINES строк в отображении
        doc = self.text_edit.document()
        if doc.blockCount() > MAX_LINES:
            cursor = self.text_edit.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor,
                                 doc.blockCount() - MAX_LINES)
            cursor.removeSelectedText()
            cursor.deleteChar()  # убрать оставшийся перевод строки

    def open_full_log(self):
        if os.path.exists(self.log_file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(self.log_file_path)))


class LogWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Журнал ошибок")
        self.resize(750, 500)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.app_tab = LogTab(APP_LOG_FILE, app_qt_handler)
        self.controller_tab = LogTab(CONTROLLER_LOG_FILE, controller_qt_handler)

        self.tabs.addTab(self.app_tab, "Ошибки приложения")
        self.tabs.addTab(self.controller_tab, "Ошибки контроллера")