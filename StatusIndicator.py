from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QLabel


# Цвета согласно ТЗ (п.6):
#   серый  - идёт процесс запуска / самодиагностики
#   зелёный - самодиагностика пройдена, ошибок не было, ПО готово к использованию
#   красный - в процессе диагностики или работы возникла ошибка
_COLORS = {
    "starting": "#9e9e9e",  # серый
    "ok": "#2ecc71",        # зелёный
    "error": "#e74c3c",     # красный
}


class StatusIndicator(QLabel):
    """
    Небольшой кружок без подписи рядом со схемой, отражающий результат
    самодиагностики ПО (запуск без клапанов/насосов, просто проверка,
    что всё инициализировалось без ошибок).

    По клику открывает Журнал ошибок - удобно перейти туда сразу,
    когда индикатор красный.
    """
    clicked = pyqtSignal()

    SIZE = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.set_state("starting")

    def set_state(self, state: str):
        color = _COLORS.get(state, _COLORS["starting"])
        self.setStyleSheet(
            f"background-color: {color}; border-radius: {self.SIZE // 2}px;"
        )
        self.setToolTip({
            "starting": "Идёт самодиагностика...",
            "ok": "ПО готово к использованию",
            "error": "Обнаружена ошибка - см. Журнал ошибок",
        }.get(state, ""))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
