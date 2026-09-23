"""
Коэффициенты статического расширения (k, q0).

Хранятся в файле EXPANSION_COEFFICIENTS_FILE_NAME рядом с программой
(рядом с .exe в собранной версии - так же, как папки "logs" и "Измерения":
файл внутри сборки PyInstaller доступен только на чтение, а таблицу нужно
уметь сохранять).

Формат файла - JSON, ровно NUM_COEFFICIENTS строк:
    {"coefficients": [{"k": 1.0, "q0": 0.0}, ...]}

При запуске программы (Engine.__init__) значения загружаются из файла; если
файла нет или он повреждён - создаётся файл со значениями по умолчанию
(DEFAULT_COEFFICIENTS - ЗАГЛУШКИ, реальные значения нужно внести через меню
"Коэффициенты статического расширения" -> "Редактировать" -> "Сохранить").

Строки таблицы соответствуют вариантам а), б), в), г) в процедуре
"Статическое расширение" (см. StaticExpansion.py).
"""
import json
import os
import sys

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
    QLabel, QHeaderView, QMessageBox,
)

from logger_setup import app_logger

EXPANSION_COEFFICIENTS_FILE_NAME = "static_expansion_coefficients.json"
NUM_COEFFICIENTS = 4
VARIANT_LETTERS = ["а", "б", "в", "г"]

# ЗАГЛУШКИ: k=1, q0=0 дают Pстат = Pисх (расширение "ничего не меняет") -
# безопасное значение, пока реальные коэффициенты не внесены в таблицу.
DEFAULT_COEFFICIENTS = [{"k": 1.0, "q0": 0.0} for _ in range(NUM_COEFFICIENTS)]


def get_coefficients_path() -> str:
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.abspath(".")
    return os.path.join(base_dir, EXPANSION_COEFFICIENTS_FILE_NAME)


def parse_number(text: str):
    """Число с запятой или точкой, в т.ч. экспоненциальная запись с русской
    "Е" ("1,5Е-3"). None, если разобрать не удалось."""
    if text is None:
        return None
    normalized = (
        str(text).strip().replace(",", ".").replace("Е", "E").replace("е", "e")
    )
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def format_number(value) -> str:
    """Короткая запись числа с русской запятой: 0,125 / 1,5E-03."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{value:.6g}".replace(".", ",").replace("e", "E")


def _validate(coefficients) -> list:
    if not isinstance(coefficients, list) or len(coefficients) != NUM_COEFFICIENTS:
        raise ValueError(f"ожидается {NUM_COEFFICIENTS} строки коэффициентов")
    result = []
    for row in coefficients:
        k = float(row["k"])
        q0 = float(row["q0"])
        if k == 0:
            raise ValueError("k не может быть равен 0")
        result.append({"k": k, "q0": q0})
    return result


def load_coefficients(path: str = None) -> list:
    """Загрузка таблицы из файла. Если файла нет/он повреждён - создаётся
    заново со значениями по умолчанию."""
    path = path or get_coefficients_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        coefficients = _validate(data["coefficients"])
        app_logger.info(f"Коэффициенты статического расширения загружены из {path}")
        return coefficients
    except FileNotFoundError:
        app_logger.warning(
            f"Файл коэффициентов {path} не найден - создан со значениями по умолчанию"
        )
    except Exception as e:
        app_logger.error(
            f"Файл коэффициентов {path} повреждён ({e}) - используются значения по умолчанию"
        )
        return [dict(row) for row in DEFAULT_COEFFICIENTS]

    coefficients = [dict(row) for row in DEFAULT_COEFFICIENTS]
    try:
        save_coefficients(coefficients, path)
    except OSError as e:
        app_logger.error(f"Не удалось создать файл коэффициентов {path}: {e}")
    return coefficients


def save_coefficients(coefficients: list, path: str = None):
    path = path or get_coefficients_path()
    coefficients = _validate(coefficients)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"coefficients": coefficients}, f, ensure_ascii=False, indent=2)
    app_logger.info(f"Коэффициенты статического расширения сохранены в {path}")


class ExpansionCoefficientsWindow(QWidget):
    """Меню "Коэффициенты статического расширения": таблица (№, k, q0) из
    4 строк. По умолчанию только просмотр; "Редактировать" разрешает правку,
    та же кнопка превращается в "Сохранить" - значения записываются в файл
    и в Engine.expansion_coefficients (сразу используются процедурой)."""

    coefficients_saved = pyqtSignal(list)

    def __init__(self, coefficients: list):
        super().__init__()
        self.setWindowTitle("Коэффициенты статического расширения")
        self.setMinimumSize(380, 260)
        self._editing = False

        layout = QVBoxLayout(self)

        self.table = QTableWidget(NUM_COEFFICIENTS, 3)
        self.table.setHorizontalHeaderLabels(["№", "k", "q0"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for row, coeff in enumerate(coefficients):
            num_item = QTableWidgetItem(f"{row + 1} ({VARIANT_LETTERS[row]})")
            num_item.setFlags(Qt.ItemIsEnabled)  # номер строки не редактируется
            self.table.setItem(row, 0, num_item)
            self.table.setItem(row, 1, QTableWidgetItem(format_number(coeff["k"])))
            self.table.setItem(row, 2, QTableWidgetItem(format_number(coeff["q0"])))
        layout.addWidget(self.table)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #e74c3c;")
        layout.addWidget(self.error_label)

        btn_row = QHBoxLayout()
        self.edit_btn = QPushButton("Редактировать")
        self.edit_btn.clicked.connect(self._on_edit_clicked)
        btn_row.addWidget(self.edit_btn)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._set_editing(False)

    def _set_editing(self, editing: bool):
        self._editing = editing
        triggers = (QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed
                    | QTableWidget.AnyKeyPressed) if editing else QTableWidget.NoEditTriggers
        self.table.setEditTriggers(triggers)
        self.edit_btn.setText("Сохранить" if editing else "Редактировать")

    def _on_edit_clicked(self):
        if not self._editing:
            self.error_label.setText("")
            self._set_editing(True)
            return

        coefficients = []
        for row in range(NUM_COEFFICIENTS):
            k = parse_number(self.table.item(row, 1).text())
            q0 = parse_number(self.table.item(row, 2).text())
            if k is None or q0 is None:
                self.error_label.setText(f"Строка {row + 1}: некорректное число")
                return
            if k == 0:
                self.error_label.setText(f"Строка {row + 1}: k не может быть равен 0")
                return
            coefficients.append({"k": k, "q0": q0})

        try:
            save_coefficients(coefficients)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить файл коэффициентов:\n{e}")
            return

        self.error_label.setText("")
        self._set_editing(False)
        self.coefficients_saved.emit(coefficients)
