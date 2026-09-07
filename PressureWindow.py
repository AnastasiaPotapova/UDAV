import re
from typing import Optional

from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QPushButton, QLabel,
)

# ТЗ_к_ПО_2.docx, п.2: диапазон значений давления, которые можно задать
# через это окно - от 1Е-1 (0,1 Па) до 10Е5 (1 000 000 Па).
MIN_PRESSURE_PA = 1e-1
MAX_PRESSURE_PA = 10 * 10 ** 5

_NUMBER_RE = re.compile(r"[+-]?\d+(\.\d+)?([eE][+-]?\d+)?")


def parse_pressure(text: str) -> Optional[float]:
    """
    Разбирает значение давления, введённое в мантиссо-экспоненциальной
    нотации (например "1Е-1", "10E5"), либо простым числом ("1013,25") -
    см. ТЗ_к_ПО_2.docx, п.2.

    Буква "Е"/"е" на этом ПО исторически вводится с русской раскладки
    клавиатуры, поэтому кириллическая и латинская буквы распознаются
    одинаково. Запятая трактуется как десятичный разделитель.
    """
    if not text:
        return None

    normalized = (
        text.strip()
        .replace(",", ".")
        .replace("Е", "E")  # русская "Е" -> латинская
        .replace("е", "e")  # русская "е" -> латинская
    )

    if not _NUMBER_RE.fullmatch(normalized):
        return None

    try:
        return float(normalized)
    except ValueError:
        return None


class PressureSetWindow(QWidget):
    """
    Окно "Установка давления" (ТЗ_к_ПО_2.docx, п.2).

    Открывается по кнопке "Установка давления" в левой панели. По кнопке
    "Ок" запускается процесс расширения и окно сразу закрывается - ТЗ
    прямо просит не добавлять здесь ещё одно окно-подтверждение ("лишние
    движения по закрытию окон никто не любит"). Кнопка "Завершить"
    закрывает окно без запуска процесса.

    Установленное значение контролируется оператором по Р стат. в нижней
    панели значений (см. MainWindow._build_values_bar) - отдельного
    индикатора в этом окне ТЗ не требует.
    """
    pressure_confirmed = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Установка давления")
        self.setFixedSize(340, 160)
        self.setWindowModality(Qt.ApplicationModal)

        layout = QVBoxLayout(self)

        form_layout = QFormLayout()
        input_row = QHBoxLayout()
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("например, 10 или 1Е-1")
        self.value_edit.returnPressed.connect(self._on_ok)
        input_row.addWidget(self.value_edit)
        input_row.addWidget(QLabel("Па"))
        form_layout.addRow("Задать Р:", input_row)
        layout.addLayout(form_layout)

        hint = QLabel(f"Диапазон: от {MIN_PRESSURE_PA:g} до {MAX_PRESSURE_PA:g} Па")
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #e74c3c;")
        layout.addWidget(self.error_label)

        layout.addStretch()

        btn_row = QHBoxLayout()
        self.ok_btn = QPushButton("Ок")
        self.ok_btn.clicked.connect(self._on_ok)
        self.finish_btn = QPushButton("Завершить")
        self.finish_btn.setToolTip("Закрыть окно без запуска установки давления")
        self.finish_btn.clicked.connect(self.close)
        btn_row.addWidget(self.ok_btn)
        btn_row.addWidget(self.finish_btn)
        layout.addLayout(btn_row)

    def _on_ok(self):
        value = parse_pressure(self.value_edit.text())
        if value is None:
            self.error_label.setText("Некорректное значение давления")
            return
        if not (MIN_PRESSURE_PA <= value <= MAX_PRESSURE_PA):
            self.error_label.setText(
                f"Значение должно быть в диапазоне от {MIN_PRESSURE_PA:g} до {MAX_PRESSURE_PA:g} Па"
            )
            return

        # запускаем процесс установки давления и сразу закрываем окно -
        # без доп. окна-подтверждения (ТЗ_к_ПО_2.docx, п.2)
        self.pressure_confirmed.emit(value)
        self.close()
