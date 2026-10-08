"""
Процедура "Метрологическая оценка" (кнопка в левой панели MainWindow).

1. Оператор отмечает флажками в таблице 2x2 места установки исследуемых СИ:
       №1 клапан V6            №2 клапан V7
       №3 фланец над клапаном V6   №4 фланец над клапаном V7
2. Таблица данных по выбранным СИ (поля заполняет оператор, могут быть пустыми):
   №, расположение, наименование полное/сокращённое, заводской №,
   вторичный электронный блок (контроллер) и его заводской №,
   первичный измерительный преобразователь (датчик) и его заводской №,
   заказчик, условия окружающей среды (давление, температура, влажность).
3. Сама поверка (цикл по точкам давления):
   а) оператор выбирает способ: напрямую ("Установка давления") или
      статическим расширением;
   б) вводится давление, запускается тот же процесс, что и по кнопкам
      "Установка давления" / "Статическое расширение";
   в) окно ввода показаний СИ (2x2, активны только выбранные места) и
      слева показание эталонного датчика (подставляется автоматически, на
      момент нажатия "Сохранить"); "Сохранить" запоминает точку;
   г) окошко: задать следующее давление или закончить поверку.
4. По завершении всё пишется в CSV "Поверка <дата_время>.csv" (папка
   "Поверка" рядом с программой/.exe, формат как у файлов "Измерения":
   разделитель ";", десятичная запятая, UTF-8 с BOM).

Эталон: при установке напрямую - P2 (МИДА-15), при статическом расширении -
последнее рассчитанное Pстат (Engine.static_pressure).
"""
import os
import sys
import textwrap
from datetime import datetime

from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QCheckBox, QPushButton,
    QTableWidget, QTableWidgetItem, QStackedWidget, QLineEdit, QGroupBox, QMessageBox,
    QHeaderView,
)

from ExpansionCoefficients import parse_number
from logger_setup import app_logger
from pressure_format import format_p2, format_pstat
from PressureWindow import PressureSetWindow
from StartStopSequencer import _read_sensor
from StaticExpansion import StaticExpansionSetupWindow, StaticExpansionRunner

VERIFICATION_DIR_NAME = "Поверка"
SEPARATOR = ";"

# № -> расположение (сетка 2x2: (строка, столбец))
POSITIONS = {
    1: "Клапан V6",
    2: "Клапан V7",
    3: "Фланец над клапаном V6",
    4: "Фланец над клапаном V7",
}
GRID = {1: (0, 0), 2: (0, 1), 3: (1, 0), 4: (1, 1)}

# колонки таблицы СИ после "№" и "Расположение" (ключ, заголовок)
DEVICE_FIELDS = [
    ("full_name", "Наименование полное"),
    ("short_name", "Наименование сокращённое"),
    ("serial", "Заводской номер"),
    ("controller_name", "Наименование вторичного электронного блока (контроллера)"),
    ("controller_serial", "Заводской номер контроллера"),
    ("sensor_name", "Наименование первичного измерительного преобразователя (датчика)"),
    ("sensor_serial", "Заводской номер датчика"),
    ("customer", "Заказчик"),
    ("conditions", "Условия окружающей среды (давление, температура, влажность)"),
]

# ширина (в символах), по которой переносятся заголовки столбцов таблицы СИ
HEADER_WRAP_WIDTH = 18

METHOD_DIRECT = "Напрямую"
METHOD_EXPANSION = "Статическое расширение"


def get_verification_dir() -> str:
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.abspath(".")
    return os.path.join(base_dir, VERIFICATION_DIR_NAME)


def _fmt_pressure(value) -> str:
    try:
        return f"{float(value):.6E}".replace(".", ",")
    except (TypeError, ValueError):
        return ""


def _csv_cell(text) -> str:
    text = "" if text is None else str(text)
    if SEPARATOR in text or '"' in text or "\n" in text:
        text = '"' + text.replace('"', '""') + '"'
    return text


# ---------------------------------------------------------------------------
# 1-2. Выбор мест установки и таблица СИ
# ---------------------------------------------------------------------------
class MetrologySetupWindow(QWidget):
    """confirmed(list): [{"num": 1, "location": "...", <поля DEVICE_FIELDS>}, ...]"""

    confirmed = pyqtSignal(list)
    closed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Метрологическая оценка")
        self.setMinimumWidth(460)
        self.setWindowModality(Qt.ApplicationModal)

        layout = QVBoxLayout(self)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)
        self.pages.addWidget(self._build_positions_page())
        self.pages.addWidget(self._build_table_page())

    # --- страница 1: флажки 2x2
    def _build_positions_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Отметьте места установки исследуемых СИ:"))

        grid = QGridLayout()
        self.checks = {}
        for num, (row, col) in GRID.items():
            cb = QCheckBox(f"№{num}  {POSITIONS[num]}")
            cb.toggled.connect(self._on_checks_changed)
            self.checks[num] = cb
            grid.addWidget(cb, row, col)
        layout.addLayout(grid)

        self.positions_error = QLabel("")
        self.positions_error.setStyleSheet("color: #e74c3c;")
        layout.addWidget(self.positions_error)
        layout.addStretch()

        row = QHBoxLayout()
        self.next_btn = QPushButton("Далее")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self._on_positions_next)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.close)
        row.addWidget(self.next_btn)
        row.addWidget(cancel)
        layout.addLayout(row)
        return page

    def _selected(self):
        return [n for n in sorted(self.checks) if self.checks[n].isChecked()]

    def _on_checks_changed(self):
        self.next_btn.setEnabled(bool(self._selected()))

    def _on_positions_next(self):
        selected = self._selected()
        if not selected:
            self.positions_error.setText("Выберите хотя бы одно место установки")
            return
        self.positions_error.setText("")
        self._fill_table(selected)
        self.setMinimumSize(1100, 320)
        self.resize(1250, 360)
        self.pages.setCurrentIndex(1)

    # --- страница 2: таблица СИ
    def _build_table_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Данные исследуемых СИ (поля можно оставить пустыми):"))

        self.table = QTableWidget(0, 2 + len(DEVICE_FIELDS))
        # заголовки длинные - переносим по словам, чтобы читались целиком
        self.table.setHorizontalHeaderLabels(
            ["№", "Расположение"]
            + [textwrap.fill(title, HEADER_WRAP_WIDTH) for _, title in DEVICE_FIELDS]
        )
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setDefaultSectionSize(150)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 170)
        layout.addWidget(self.table)

        row = QHBoxLayout()
        back = QPushButton("Назад")
        back.clicked.connect(self._on_back)
        start = QPushButton("Начать поверку")
        start.clicked.connect(self._on_start)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.close)
        row.addWidget(back)
        row.addStretch()
        row.addWidget(start)
        row.addWidget(cancel)
        layout.addLayout(row)
        return page

    def _on_back(self):
        self.setMinimumSize(460, 0)
        self.resize(460, 160)
        self.pages.setCurrentIndex(0)

    def _fill_table(self, selected):
        # при возврате "Назад" и повторном "Далее" уже введённое сохраняем
        old = {d["num"]: d for d in self._read_table()} if self.table.rowCount() else {}
        self.table.setRowCount(len(selected))
        for r, num in enumerate(selected):
            num_item = QTableWidgetItem(str(num))
            num_item.setFlags(Qt.ItemIsEnabled)
            loc_item = QTableWidgetItem(POSITIONS[num])
            loc_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 0, num_item)
            self.table.setItem(r, 1, loc_item)
            for c, (key, _) in enumerate(DEVICE_FIELDS):
                self.table.setItem(r, 2 + c, QTableWidgetItem(old.get(num, {}).get(key, "")))
        self.table.resizeRowsToContents()

    def _read_table(self):
        devices = []
        for r in range(self.table.rowCount()):
            num = int(self.table.item(r, 0).text())
            dev = {"num": num, "location": POSITIONS[num]}
            for c, (key, _) in enumerate(DEVICE_FIELDS):
                item = self.table.item(r, 2 + c)
                dev[key] = item.text().strip() if item else ""
            devices.append(dev)
        return devices

    def _on_start(self):
        self.table.clearFocus()
        devices = self._read_table()
        self.confirmed.emit(devices)
        self.close()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# 3в. Ввод показаний СИ
# ---------------------------------------------------------------------------
class ReadingsWindow(QWidget):
    """saved(dict): {"method", "p_set", "reference", "readings": {num: float}}"""

    saved = pyqtSignal(dict)
    cancelled = pyqtSignal()

    def __init__(self, selected_nums, method, p_set, reference_getter, reference_caption):
        super().__init__()
        self.setWindowTitle("Поверка: показания СИ")
        self.setMinimumWidth(620)
        self.method = method
        self.p_set = p_set
        self.reference_getter = reference_getter
        self._done = False

        layout = QVBoxLayout(self)
        self.head = QLabel(f"Способ: {method};  заданное давление: "
                           f"{str(f'{p_set:g}').replace('.', ',')} Па")
        self.head.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.head)

        body = QHBoxLayout()
        ref_box = QGroupBox(reference_caption)
        ref_layout = QVBoxLayout(ref_box)
        self.ref_label = QLabel("—")
        self.ref_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        ref_layout.addWidget(self.ref_label)
        ref_layout.addStretch()
        body.addWidget(ref_box)

        dev_box = QGroupBox("Показания исследуемых СИ, Па")
        grid = QGridLayout(dev_box)
        self.edits = {}
        for num, (row, col) in GRID.items():
            cell = QVBoxLayout()
            cell.addWidget(QLabel(f"№{num}  {POSITIONS[num]}"))
            edit = QLineEdit()
            edit.setPlaceholderText("например, 1,25Е2")
            edit.setEnabled(num in selected_nums)
            cell.addWidget(edit)
            grid.addLayout(cell, row, col)
            self.edits[num] = edit
        body.addWidget(dev_box, stretch=1)
        layout.addLayout(body)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #e74c3c;")
        layout.addWidget(self.error_label)

        row = QHBoxLayout()
        self.save_btn = QPushButton("Сохранить")
        self.save_btn.clicked.connect(self._on_save)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self._on_cancel)
        row.addStretch()
        row.addWidget(self.save_btn)
        row.addWidget(cancel)
        layout.addLayout(row)

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._update_reference)
        self.timer.start()
        self._update_reference()

    def _update_reference(self):
        value = self.reference_getter()
        self.ref_label.setText(format_pstat(value) if value is not None else "—")

    def _on_save(self):
        reference = self.reference_getter()
        if reference is None:
            self.error_label.setText("Нет показаний эталона - сохранить нельзя")
            return
        readings = {}
        for num, edit in self.edits.items():
            if not edit.isEnabled():
                continue
            value = parse_number(edit.text())
            if value is None:
                self.error_label.setText(f"СИ №{num}: введите число")
                return
            readings[num] = value
        self._done = True
        self.timer.stop()
        self.saved.emit({"method": self.method, "p_set": self.p_set,
                         "reference": reference, "readings": readings})
        self.close()

    def _on_cancel(self):
        self.close()

    def closeEvent(self, event):
        self.timer.stop()
        if not self._done:
            self._done = True
            self.cancelled.emit()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Управление процедурой
# ---------------------------------------------------------------------------
class MetrologyController(QObject):
    finished = pyqtSignal()

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.devices = []
        self.records = []
        self.saved_path = None
        self._runner = None
        self._awaiting = False      # ждём результат подокна (Ок) - иначе это отмена
        self._windows = []

    # --- запуск
    def start(self):
        self.setup = MetrologySetupWindow()
        self.setup.confirmed.connect(self._on_devices)
        self.setup.closed.connect(self._on_setup_closed)
        self._setup_ok = False
        self.setup.show()

    def _on_devices(self, devices):
        self._setup_ok = True
        self.devices = devices
        app_logger.info("Метрологическая оценка: СИ %s", [d["num"] for d in devices])
        QTimer.singleShot(0, self._ask_method)

    def _on_setup_closed(self):
        if not self._setup_ok:
            self.finished.emit()

    # --- 3а. выбор способа
    def _ask_method(self):
        box = QMessageBox()
        box.setWindowTitle("Поверка")
        box.setText(f"Точка №{len(self.records) + 1}. Как задать давление?")
        direct = box.addButton(METHOD_DIRECT, QMessageBox.AcceptRole)
        expansion = box.addButton(METHOD_EXPANSION, QMessageBox.AcceptRole)
        end_text = "Закончить поверку" if self.records else "Отмена"
        end = box.addButton(end_text, QMessageBox.RejectRole)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is direct:
            self._start_direct()
        elif clicked is expansion:
            self._start_expansion()
        else:
            self._finish()

    # --- 3б. установка давления
    def _start_direct(self):
        self._awaiting = True
        self._p_win = PressureSetWindow()
        self._p_win.pressure_confirmed.connect(self._on_direct_pressure)
        self._p_win.closed.connect(self._on_sub_closed)
        self._p_win.show()

    def _on_direct_pressure(self, value):
        self._awaiting = False
        self.engine.set_pressure(value)
        self._open_readings(METHOD_DIRECT, value,
                            lambda: _read_sensor(self.engine, "P2"), "Эталон: Р2")

    def _start_expansion(self):
        self._awaiting = True
        self._e_win = StaticExpansionSetupWindow(self.engine.expansion_coefficients)
        self._e_win.start_requested.connect(self._on_expansion_params)
        self._e_win.closed.connect(self._on_sub_closed)
        self._e_win.show()

    def _on_expansion_params(self, params):
        self._awaiting = False
        self.engine.static_pressure = None
        self._runner = StaticExpansionRunner(self.engine, params, self)
        self._runner.finished.connect(lambda: self._on_expansion_finished(params["p_target"]))
        self._runner.start()

    def _on_expansion_finished(self, p_target):
        self._runner = None
        self._open_readings(METHOD_EXPANSION, p_target,
                            lambda: self.engine.static_pressure, "Эталон: Р стат.")

    def _on_sub_closed(self):
        # окно закрыто без "Ок" - возвращаемся к выбору способа
        if self._awaiting:
            self._awaiting = False
            QTimer.singleShot(0, self._ask_method)

    # --- 3в. показания
    def _open_readings(self, method, p_set, getter, caption):
        nums = {d["num"] for d in self.devices}
        self.readings_win = ReadingsWindow(nums, method, p_set, getter, caption)
        self.readings_win.saved.connect(self._on_saved)
        self.readings_win.cancelled.connect(self._on_readings_cancelled)
        self.readings_win.show()

    def _on_saved(self, record):
        self.records.append(record)
        app_logger.info("Метрологическая оценка: точка %s сохранена: %s", len(self.records), record)
        QTimer.singleShot(0, self._ask_next)

    def _on_readings_cancelled(self):
        QTimer.singleShot(0, self._ask_method)

    # --- 3г. следующее давление или конец
    def _ask_next(self):
        box = QMessageBox()
        box.setWindowTitle("Поверка")
        box.setText("Точка сохранена.")
        nxt = box.addButton("Задать следующее давление", QMessageBox.AcceptRole)
        end = box.addButton("Закончить поверку", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is nxt:
            self._ask_method()
        else:
            self._finish()

    # --- запись в файл
    def _finish(self):
        if self.records:
            try:
                self.saved_path = self.save_file()
                QMessageBox.information(None, "Поверка", f"Результаты сохранены:\n{self.saved_path}")
            except OSError as e:
                app_logger.error("Не удалось сохранить файл поверки: %s", e)
                QMessageBox.critical(None, "Поверка", f"Не удалось сохранить файл:\n{e}")
        self.finished.emit()

    def abort(self):
        """Закрытие программы посреди поверки: сохраняем, что успели."""
        if self._runner is not None:
            self._runner.stop()
        if self.records and self.saved_path is None:
            try:
                self.save_file()
            except OSError:
                pass

    def save_file(self) -> str:
        directory = get_verification_dir()
        os.makedirs(directory, exist_ok=True)
        now = datetime.now()
        path = os.path.join(directory, f"Поверка {now.strftime('%Y-%m-%d_%H-%M-%S')}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            for line in self.build_rows(now):
                f.write(SEPARATOR.join(_csv_cell(c) for c in line) + "\r\n")
        app_logger.info("Файл поверки сохранён: %s", path)
        return path

    def build_rows(self, now=None):
        now = now or datetime.now()
        rows = [["Поверка", now.strftime("%d.%m.%Y %H:%M:%S")], []]
        rows.append(["СИ"])
        rows.append(["№", "Расположение"] + [title for _, title in DEVICE_FIELDS])
        for d in self.devices:
            rows.append([d["num"], d["location"]] + [d.get(k, "") for k, _ in DEVICE_FIELDS])
        rows.append([])
        rows.append(["Измерения"])
        nums = [d["num"] for d in self.devices]
        rows.append(["№ точки", "Способ", "Задано, Па", "Эталон, Па"]
                    + [f"СИ №{n}, Па" for n in nums])
        for i, rec in enumerate(self.records, 1):
            rows.append([i, rec["method"], _fmt_pressure(rec["p_set"]), _fmt_pressure(rec["reference"])]
                        + [_fmt_pressure(rec["readings"].get(n)) for n in nums])
        return rows
