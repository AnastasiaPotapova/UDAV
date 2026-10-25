import struct

from PyQt5.QtCore import pyqtSlot, pyqtSignal
from PyQt5.QtWidgets import *


# Порядок байт в EEPROM — little-endian (как и во всём протоколе):
# например, 00 00 BE 43 = float32 380.0
EEPROM_TYPES = {
    #  имя        формат  размер
    "uint8":   ("<B", 1),
    "int8":    ("<b", 1),
    "uint16":  ("<H", 2),
    "int16":   ("<h", 2),
    "uint32":  ("<I", 4),
    "int32":   ("<i", 4),
    "float32": ("<f", 4),
}

AUTO_TYPE = "Авто"
HEX_TYPE = "hex-байты"

# Защищённые области EEPROM: перед записью в них спрашивается подтверждение
PROTECTED_RANGES = [
    (100, 115, "калибровочные коэффициенты температуры"),
]


def auto_type_for_size(size: int) -> str:
    """Тип по умолчанию для прочитанного размера: 1 → uint8, 2 → uint16,
    4 и кратные 4 → float32 (по 4 байта на значение), иначе — побайтово."""
    if size == 2:
        return "uint16"
    if size >= 4 and size % 4 == 0:
        return "float32"
    return "uint8"


def format_number(value) -> str:
    if isinstance(value, float):
        text = f"{value:.7g}"
        if "e" not in text and "." not in text and text not in ("nan", "inf", "-inf"):
            text += ".0"
        return text.replace(".", ",")
    return str(value)


def decode_values(data: bytes, type_name: str):
    """Список (смещение, значение) для data, интерпретированных как type_name.
    Хвост, не кратный размеру типа, возвращается отдельно."""
    fmt, size = EEPROM_TYPES[type_name]
    values = []
    whole = len(data) - len(data) % size
    for off in range(0, whole, size):
        values.append((off, struct.unpack(fmt, data[off:off + size])[0]))
    return values, data[whole:]


def encode_values(text: str, type_name: str) -> bytes:
    """Значения через пробел (или ';') → байты. Для float допускается запятая."""
    fmt, _ = EEPROM_TYPES[type_name]
    parts = text.replace(";", " ").split()
    if not parts:
        raise ValueError("не заданы данные")
    out = b""
    for part in parts:
        if type_name == "float32":
            value = float(part.replace(",", "."))
        else:
            value = int(part, 0)  # 10, 0x0A, 0b1010
        try:
            out += struct.pack(fmt, value)
        except struct.error:
            raise ValueError(f"значение {part} не помещается в {type_name}")
    return out


class EepromWindow(QWidget):
    eeprom_read_request = pyqtSignal(int, int)   # address, num_bytes
    eeprom_write_request = pyqtSignal(int, bytes)  # address, data

    def __init__(self, is_connected=None):
        super().__init__()
        self.setWindowTitle("Данные EEPROM")
        # is_connected: необязательный callable() -> bool, чтобы явно
        # сказать пользователю "нет подключения" вместо тихого бездействия
        # (см. MainWindow.ReadEeprom)
        self.is_connected = is_connected
        self.read_address = 0     # адрес начала последнего чтения
        self.read_data = b""      # последние прочитанные байты
        layout = QVBoxLayout(self)
        self.setLayout(layout)

        # --- чтение ---
        read_layout = QHBoxLayout()
        self.start_input = QLineEdit()
        self.end_input = QLineEdit()
        self.start_input.setPlaceholderText("Начальный адрес")
        self.end_input.setPlaceholderText("Конечный адрес")
        read_layout.addWidget(QLabel("От:"))
        read_layout.addWidget(self.start_input)
        read_layout.addWidget(QLabel("До:"))
        read_layout.addWidget(self.end_input)
        layout.addLayout(read_layout)

        self.generate_button = QPushButton("Прочитать")
        self.generate_button.clicked.connect(self.read_eeprom_command)
        layout.addWidget(self.generate_button)

        # --- запись ---
        write_layout = QHBoxLayout()
        self.write_address_input = QLineEdit()
        self.write_address_input.setPlaceholderText("Адрес записи")
        self.write_type_combo = QComboBox()
        self.write_type_combo.addItems([HEX_TYPE] + list(EEPROM_TYPES))
        self.write_type_combo.currentTextChanged.connect(self._update_write_placeholder)
        self.write_data_input = QLineEdit()
        self.write_data_input.textChanged.connect(self._update_write_preview)
        write_layout.addWidget(QLabel("Адрес:"))
        write_layout.addWidget(self.write_address_input)
        write_layout.addWidget(QLabel("Тип:"))
        write_layout.addWidget(self.write_type_combo)
        write_layout.addWidget(QLabel("Данные:"))
        write_layout.addWidget(self.write_data_input, stretch=1)
        layout.addLayout(write_layout)

        self.write_preview_label = QLabel("")
        layout.addWidget(self.write_preview_label)

        self.write_button = QPushButton("Записать")
        self.write_button.clicked.connect(self.write_eeprom_command)
        layout.addWidget(self.write_button)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # --- интерпретация прочитанного ---
        interp_layout = QHBoxLayout()
        interp_layout.addWidget(QLabel("Интерпретация:"))
        self.interp_combo = QComboBox()
        self.interp_combo.addItems([AUTO_TYPE] + list(EEPROM_TYPES))
        self.interp_combo.currentTextChanged.connect(self._update_interpretation)
        interp_layout.addWidget(self.interp_combo)
        interp_layout.addStretch(1)
        layout.addLayout(interp_layout)

        self.interp_table = QTableWidget()
        self.interp_table.setColumnCount(3)
        self.interp_table.setHorizontalHeaderLabels(["Адрес", "Тип", "Значение"])
        self.interp_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.interp_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.interp_table)

        # --- сырые байты ---
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Адрес", "0x", "dec"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)

        self._update_write_placeholder()

    # ------------------------------------------------------------------
    # чтение
    # ------------------------------------------------------------------
    @pyqtSlot(list)
    def handle_data(self, data_list: list):
        self.read_data = bytes(data_list)
        self.table.setRowCount(len(data_list))
        for i, val in enumerate(data_list):
            self.table.setItem(i, 0, QTableWidgetItem(str(self.read_address + i)))
            self.table.setItem(i, 1, QTableWidgetItem(f"0x{val:02X}"))
            self.table.setItem(i, 2, QTableWidgetItem(str(val)))
        self.status_label.setText(f"Прочитано {len(data_list)} байт")
        self._update_interpretation()

    def _update_interpretation(self, *_):
        data = self.read_data
        self.interp_table.setRowCount(0)
        if not data:
            return

        choice = self.interp_combo.currentText()
        type_name = auto_type_for_size(len(data)) if choice == AUTO_TYPE else choice
        values, tail = decode_values(data, type_name)

        rows = [(self.read_address + off, type_name, format_number(v)) for off, v in values]
        if tail:
            tail_addr = self.read_address + len(data) - len(tail)
            rows.append((tail_addr, "остаток",
                         " ".join(f"{b:02X}" for b in tail) + " (не хватает байт до полного значения)"))

        self.interp_table.setRowCount(len(rows))
        for r, (addr, typ, text) in enumerate(rows):
            self.interp_table.setItem(r, 0, QTableWidgetItem(str(addr)))
            self.interp_table.setItem(r, 1, QTableWidgetItem(typ))
            self.interp_table.setItem(r, 2, QTableWidgetItem(text))

    def read_eeprom_command(self):
        if self.is_connected is not None and not self.is_connected():
            self.status_label.setText("Ошибка: нет подключения к порту (Настройки -> Подключение)")
            return

        try:
            start = int(self.start_input.text())
            end = int(self.end_input.text())
            if start > end or start < 0:
                raise ValueError
        except ValueError:
            self.status_label.setText("Ошибка: некорректный диапазон адресов")
            return

        count = end - start + 1
        if count > 255:
            self.status_label.setText("Ошибка: максимум 255 байт за раз")
            return

        self.read_address = start
        self.status_label.setText(f"Запрос чтения: {start}..{end}")
        self.eeprom_read_request.emit(start, count)

    # ------------------------------------------------------------------
    # запись
    # ------------------------------------------------------------------
    def _update_write_placeholder(self, *_):
        if self.write_type_combo.currentText() == HEX_TYPE:
            self.write_data_input.setPlaceholderText("Байты через пробел, напр. 01 A0 FF")
        elif self.write_type_combo.currentText() == "float32":
            self.write_data_input.setPlaceholderText("Числа через пробел, напр. 380,0 1,5e-3")
        else:
            self.write_data_input.setPlaceholderText("Числа через пробел, напр. 10 0x1F")
        self._update_write_preview()

    def _parse_write_data(self) -> bytes:
        raw_text = self.write_data_input.text().strip()
        if not raw_text:
            raise ValueError("не заданы данные для записи")
        type_name = self.write_type_combo.currentText()
        if type_name == HEX_TYPE:
            try:
                return bytes(int(b, 16) for b in raw_text.split())
            except ValueError:
                raise ValueError("данные должны быть в hex, напр. '01 A0 FF'")
        try:
            return encode_values(raw_text, type_name)
        except ValueError as e:
            msg = str(e)
            if not msg.startswith(("значение", "не заданы")):
                msg = f"некорректное число для типа {type_name}"
            raise ValueError(msg)

    def _update_write_preview(self, *_):
        if not self.write_data_input.text().strip():
            self.write_preview_label.setText("")
            return
        try:
            data = self._parse_write_data()
            self.write_preview_label.setText(
                f"Будет записано {len(data)} байт: " + " ".join(f"{b:02X}" for b in data))
        except ValueError as e:
            self.write_preview_label.setText(f"Ошибка: {e}")

    def _confirm_protected(self, address: int, length: int) -> bool:
        end = address + length - 1
        for lo, hi, what in PROTECTED_RANGES:
            if address <= hi and end >= lo:
                res = QMessageBox.warning(
                    self, "Защищённая область EEPROM",
                    f"Запись затрагивает адреса {max(address, lo)}–{min(end, hi)}: "
                    f"{what} (адреса {lo}–{hi}).\n\nВсё равно записать?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if res != QMessageBox.Yes:
                    return False
        return True

    def write_eeprom_command(self):
        if self.is_connected is not None and not self.is_connected():
            self.status_label.setText("Ошибка: нет подключения к порту (Настройки -> Подключение)")
            return

        try:
            address = int(self.write_address_input.text())
            if address < 0:
                raise ValueError
        except ValueError:
            self.status_label.setText("Ошибка: некорректный адрес записи")
            return

        try:
            data = self._parse_write_data()
        except ValueError as e:
            self.status_label.setText(f"Ошибка: {e}")
            return

        if not data:
            self.status_label.setText("Ошибка: пустые данные")
            return

        if not self._confirm_protected(address, len(data)):
            self.status_label.setText("Запись отменена")
            return

        self.status_label.setText(
            f"Запись {len(data)} байт по адресу {address}: " + " ".join(f"{b:02X}" for b in data))
        self.eeprom_write_request.emit(address, data)

    def save_table(self):
        rows = self.table.rowCount()
        cols = self.table.columnCount()
        result = [[self.table.item(r, c).text() if self.table.item(r, c) else "" for c in range(cols)] for r in range(rows)]
        print("EEPROM сохранены:", result)
