"""
Запись измерений в файл во время работы установки.

Формат - CSV (открывается Excel двойным щелчком, занимает минимум места):
    - разделитель ";"      - так Excel с русскими региональными настройками
                             сразу раскладывает данные по столбцам;
    - десятичная запятая   - Excel воспринимает значения как числа, а не текст;
    - кодировка UTF-8 с BOM - иначе Excel покажет кириллицу в заголовке
                             "кракозябрами".

Столбцы: Время; P1; P2; P3; T1; T2; T MCU внутр.; T MCU внешн.
Давления пишутся в Па с полной точностью в экспоненциальной записи
(например 1,234567E-02), температуры - в °C с одним знаком после запятой,
уже с учётом масштаба контроллера (как в нижней панели значений).

Имя файла - дата и время начала записи: "2026-09-23_21-52-03.csv"
(двоеточия в именах файлов Windows не допускает). Файлы складываются в папку
"Измерения" рядом с программой (рядом с .exe в собранной версии - так же,
как папка "logs", см. logger_setup.py).

Когда пишется (см. StartStopController в StartStopSequencer.py):
    - запись начинается после УСПЕШНОГО завершения процедуры "Запуск";
    - запись останавливается перед началом процедуры "Остановка"
      (а также при закрытии программы).

Контроллер присылает опрос часто, поэтому строка пишется не на каждый пакет,
а не чаще RECORD_INTERVAL_S секунд - это и держит размер файла небольшим.
Каждая строка сразу сбрасывается на диск (flush), чтобы при аварийном
завершении программы уже записанные данные не пропали.
"""
import os
import sys
import time
from datetime import datetime

from PyQt5.QtCore import QObject

from logger_setup import app_logger

# Минимальный интервал между строками в файле, секунд.
RECORD_INTERVAL_S = 1.0

MEASUREMENTS_DIR_NAME = "Измерения"

# Какое поле exchange_packet пишется в какой столбец.
# P1/P3 - так же, как в нижней панели значений (MainWindow._update_values_bar).
# ВНИМАНИЕ: на графиках P1/P3 намеренно переставлены (см.
# claude/start-stop-sequence.md) - если в файле P1/P3 окажутся перепутаны,
# поменять местами поля здесь.
PRESSURE_COLUMNS = [
    ("P1, Па", "mida_pressure"),
    ("P2, Па", "magdischarge_pressure"),
    ("P3, Па", "thermal_pressure"),
]

# (заголовок, поле, делитель масштаба контроллера) - как в нижней панели.
TEMPERATURE_COLUMNS = [
    ("T1, °C", "temperature_channel_1", 10),
    ("T2, °C", "temperature_channel_2", 10),
    ("T MCU внутр., °C", "temperature_mcu_internal", 100),
    ("T MCU внешн., °C", "temperature_mcu_external", 10),
]

SEPARATOR = ";"


def get_measurements_dir() -> str:
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.abspath(".")
    return os.path.join(base_dir, MEASUREMENTS_DIR_NAME)


def _fmt_pressure(value) -> str:
    try:
        return f"{float(value):.6E}".replace(".", ",")
    except (TypeError, ValueError):
        return ""


def _fmt_temperature(value, scale) -> str:
    try:
        return f"{float(value) / scale:.1f}".replace(".", ",")
    except (TypeError, ValueError, ZeroDivisionError):
        return ""


class MeasurementRecorder(QObject):
    """Подписывается на Engine.packet_received и, пока запись включена,
    дописывает строки в CSV-файл текущего сеанса."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._file = None
        self._path = None
        self._last_write = 0.0
        engine.packet_received.connect(self._on_packet)

    @property
    def is_recording(self) -> bool:
        return self._file is not None

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
            name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".csv"
            path = os.path.join(folder, name)
            self._file = open(path, "w", encoding="utf-8-sig", newline="")
        except OSError as e:
            self._file = None
            app_logger.error("Не удалось начать запись измерений: %s", e)
            return

        self._path = path
        self._last_write = 0.0
        header = ["Время"] + [h for h, _ in PRESSURE_COLUMNS] + [h for h, _, _ in TEMPERATURE_COLUMNS]
        self._write_line(header)
        app_logger.info("Запись измерений начата: %s", path)

        # сразу пишем последний известный опрос, не дожидаясь следующего
        if self.engine.last_data:
            self._on_packet(self.engine.last_data)

    def stop(self):
        if not self.is_recording:
            return
        try:
            self._file.close()
        except OSError as e:
            app_logger.error("Ошибка при закрытии файла измерений: %s", e)
        app_logger.info("Запись измерений остановлена: %s", self._path)
        self._file = None

    # ------------------------------------------------------------ запись
    def _on_packet(self, data: dict):
        if not self.is_recording or data.get("__packet__") != "exchange_packet":
            return
        now = time.monotonic()
        if self._last_write and now - self._last_write < RECORD_INTERVAL_S:
            return
        self._last_write = now

        row = [datetime.now().strftime("%d.%m.%Y %H:%M:%S")]
        row += [_fmt_pressure(data.get(field)) for _, field in PRESSURE_COLUMNS]
        row += [_fmt_temperature(data.get(field), scale) for _, field, scale in TEMPERATURE_COLUMNS]
        self._write_line(row)

    def _write_line(self, cells):
        try:
            self._file.write(SEPARATOR.join(cells) + "\r\n")
            self._file.flush()
        except (OSError, ValueError) as e:
            app_logger.error("Ошибка записи измерений, запись остановлена: %s", e)
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
