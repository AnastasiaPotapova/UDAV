import logging
import os
from PyQt5.QtCore import QObject, pyqtSignal

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

APP_LOG_FILE = os.path.join(LOG_DIR, "app.log")
CONTROLLER_LOG_FILE = os.path.join(LOG_DIR, "controller.log")


class QtLogHandler(QObject, logging.Handler):
    """Хэндлер, который дублирует каждую запись лога в GUI через сигнал."""
    log_signal = pyqtSignal(str)

    def __init__(self, level=logging.NOTSET):
        QObject.__init__(self)
        logging.Handler.__init__(self, level)

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self.log_signal.emit(msg)


_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# ------------------- логгер приложения -------------------
app_logger = logging.getLogger("app")
app_logger.setLevel(logging.DEBUG)
app_logger.propagate = False

_app_file_handler = logging.FileHandler(APP_LOG_FILE, encoding="utf-8")
_app_file_handler.setFormatter(_formatter)
app_logger.addHandler(_app_file_handler)

app_qt_handler = QtLogHandler()
app_qt_handler.setFormatter(_formatter)
app_logger.addHandler(app_qt_handler)

# ------------------- логгер контроллера -------------------
controller_logger = logging.getLogger("controller")
controller_logger.setLevel(logging.DEBUG)
controller_logger.propagate = False

_controller_file_handler = logging.FileHandler(CONTROLLER_LOG_FILE, encoding="utf-8")
_controller_file_handler.setFormatter(_formatter)
controller_logger.addHandler(_controller_file_handler)

controller_qt_handler = QtLogHandler()
controller_qt_handler.setFormatter(_formatter)
controller_logger.addHandler(controller_qt_handler)