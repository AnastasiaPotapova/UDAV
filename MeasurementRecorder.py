"""
Запись измерений в Excel-файл (.xlsx) во время работы установки.

Столбцы: Время; P1; P2; P3; T1; Tproc; NI; V1; V2; V3; V4; V5; VF.
    - давления - в Па, числами (формат 0,000000E+00);
    - T1 (канал 1, /100) и Tproc (процессный канал 2, /10) - в °C, один знак
      после запятой, с тем же масштабом, что в нижней панели значений;
    - NI, V1...V5, VF - состояние: 1 - включён/открыт, 0 - выключен/закрыт.
      NI и V1...V5 берутся из телеметрии контроллера; для VF телеметрии в
      протоколе нет, поэтому пишется последнее скомандованное состояние
      (Engine.system_status).

Имя файла - дата и время начала записи: "2026-09-23_21-52-03.xlsx"
(двоеточия в именах файлов Windows не допускает). Файлы складываются в папку
"Измерения" рядом с программой (рядом с .exe в собранной версии - так же,
как папка "logs", см. logger_setup.py).

Когда пишется (см. StartStopController в StartStopSequencer.py):
    - запись начинается после УСПЕШНОГО завершения процедуры "Запуск";
    - запись останавливается перед началом процедуры "Остановка"
      (а также при закрытии программы).

Строка пишется не чаще раза в RECORD_INTERVAL_S секунд. xlsx нельзя
дописывать построчно, как CSV, поэтому книга держится в памяти и на диск
сохраняется каждые SAVE_INTERVAL_S секунд и при остановке записи: при
аварийном завершении программы теряются максимум последние SAVE_INTERVAL_S
секунд. Если файл в этот момент открыт в Excel (Windows блокирует его),
сохранение просто повторяется в следующий раз.
"""
import os
import sys
import time
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from PyQt5.QtCore import QObject

from logger_setup import app_logger

# Минимальный интервал между строками в файле, секунд.
RECORD_INTERVAL_S = 1.0
# Как часто книга сохраняется на диск, секунд.
SAVE_INTERVAL_S = 10.0

MEASUREMENTS_DIR_NAME = "Измерения"

# Какое поле exchange_packet пишется в какой столбец.
# P1/P3 - так же, как в нижней панели значений (MainWindow._update_values_bar).
# ВНИМАНИЕ: на графиках P1/P3 намеренно переставлены (см.
# claude/start-stop-sequence.md) - если в файле P1/P3 окажутся перепутаны,
# поменять местами поля здесь.
PRESSURE_COLUMNS = [
    ("P1", "mida_pressure"),
    ("P2", "magdischarge_pressure"),
    ("P3", "thermal_pressure"),
]

# (заголовок, поле, делитель масштаба контроллера) - как в нижней панели.
# Tproc - процессный температурный канал 2.
TEMPERATURE_COLUMNS = [
    ("T1", "temperature_channel_1", 100),
    ("Tproc", "temperature_channel_2", 10),
]

# Состояния: (заголовок, имя элемента)
STATE_COLUMNS = ["NI", "V1", "V2", "V3", "V4", "V5", "VF"]

TIME_FORMAT = "DD.MM.YYYY HH:MM:SS"
PRESSURE_FORMAT = "0.000000E+00"
TEMPERATURE_FORMAT = "0.0"


def get_measurements_dir() -> str:
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.abspath(".")
    return os.path.join(base_dir, MEASUREMENTS_DIR_NAME)


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _temperature(value, scale):
    try:
        return round(float(value) / scale, 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def element_state(name: str, data: dict, engine):
    """Состояние NI/V1..V5/VF: 1 или 0 (None, если узнать не удалось)."""
    if name == "NI":
        value = data.get("forvacuum_state")
    elif name in ("V1", "V3"):
        value = (data.get("du16") or {}).get(name)
    elif name == "V2":
        value = data.get("du63")
    elif name in ("V4", "V5"):
        value = (data.get("electro_valves") or {}).get(name)
    elif name == "VF":
        # телеметрии VF в протоколе нет - последнее скомандованное состояние
        value = engine.system_status.get("VF")
    else:
        value = None
    return None if value is None else int(bool(value))


class MeasurementRecorder(QObject):
    """Подписывается на Engine.packet_received и, пока запись включена,
    добавляет строки в xlsx-файл текущего сеанса."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._wb = None
        self._ws = None
        self._path = None
        self._last_write = 0.0
        self._last_save = 0.0
        self._dirty = False
        engine.packet_received.connect(self._on_packet)

    @property
    def is_recording(self) -> bool:
        return self._wb is not None

    @property
    def current_path(self):
        return self._path

    # ------------------------------------------------------------ управление
    def start(self):
        if self.is_recording:
            return
        folder = get_measurements_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".xlsx"
            path = os.path.join(folder, name)
        except OSError as e:
            app_logger.error("Не удалось начать запись измерений: %s", e)
            return

        wb = Workbook()
        ws = wb.active
        ws.title = "Измерения"
        header = (["Время"] + [h for h, _ in PRESSURE_COLUMNS]
                  + [h for h, _, _ in TEMPERATURE_COLUMNS] + STATE_COLUMNS)
        ws.append(header)
        for col in range(1, len(header) + 1):
            ws.cell(row=1, column=col).font = Font(bold=True)
            ws.column_dimensions[get_column_letter(col)].width = 20 if col == 1 else 13
        ws.freeze_panes = "A2"

        self._wb, self._ws, self._path = wb, ws, path
        self._last_write = 0.0
        self._last_save = 0.0
        self._dirty = True
        if not self._save():
            # не удалось даже создать файл - запись не ведём
            self._wb = self._ws = self._path = None
            return
        app_logger.info("Запись измерений начата: %s", path)

        # сразу пишем последний известный опрос, не дожидаясь следующего
        if self.engine.last_data:
            self._on_packet(self.engine.last_data)

    def stop(self):
        if not self.is_recording:
            return
        self._save()
        app_logger.info("Запись измерений остановлена: %s", self._path)
        self._wb = self._ws = None

    # ------------------------------------------------------------ запись
    def _on_packet(self, data: dict):
        if not self.is_recording or data.get("__packet__") != "exchange_packet":
            return
        now = time.monotonic()
        if self._last_write and now - self._last_write < RECORD_INTERVAL_S:
            return
        self._last_write = now

        row = [datetime.now()]
        row += [_number(data.get(field)) for _, field in PRESSURE_COLUMNS]
        row += [_temperature(data.get(field), scale) for _, field, scale in TEMPERATURE_COLUMNS]
        row += [element_state(name, data, self.engine) for name in STATE_COLUMNS]
        self._ws.append(row)

        r = self._ws.max_row
        self._ws.cell(row=r, column=1).number_format = TIME_FORMAT
        for col in range(2, 2 + len(PRESSURE_COLUMNS)):
            self._ws.cell(row=r, column=col).number_format = PRESSURE_FORMAT
        first_t = 2 + len(PRESSURE_COLUMNS)
        for col in range(first_t, first_t + len(TEMPERATURE_COLUMNS)):
            self._ws.cell(row=r, column=col).number_format = TEMPERATURE_FORMAT
        self._dirty = True

        if now - self._last_save >= SAVE_INTERVAL_S:
            self._save()

    def _save(self) -> bool:
        if not self._dirty:
            return True
        try:
            self._wb.save(self._path)
        except OSError as e:
            # например, файл открыт в Excel - повторим при следующем сохранении
            app_logger.error("Не удалось сохранить файл измерений (%s), повторим позже: %s", self._path, e)
            self._last_save = time.monotonic()
            return False
        self._last_save = time.monotonic()
        self._dirty = False
        return True
