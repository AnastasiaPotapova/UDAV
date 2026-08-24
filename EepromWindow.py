from PyQt5.QtCore import pyqtSlot, pyqtSignal
from PyQt5.QtWidgets import *


class EepromWindow(QWidget):
    eeprom_read_request = pyqtSignal(int, int)   # address, num_bytes
    eeprom_write_request = pyqtSignal(int, bytes)  # address, data

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Данные EEPROM")
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
        self.write_data_input = QLineEdit()
        self.write_data_input.setPlaceholderText("Байты через пробел, напр. 01 A0 FF")
        write_layout.addWidget(QLabel("Адрес:"))
        write_layout.addWidget(self.write_address_input)
        write_layout.addWidget(QLabel("Данные:"))
        write_layout.addWidget(self.write_data_input)
        layout.addLayout(write_layout)

        self.write_button = QPushButton("Записать")
        self.write_button.clicked.connect(self.write_eeprom_command)
        layout.addWidget(self.write_button)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.table = QTableWidget()
        layout.addWidget(self.table)

    @pyqtSlot(list)
    def handle_data(self, data_list: list):
        self.table.setRowCount(len(data_list))
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Индекс", "0x", "dec"])
        for i, val in enumerate(data_list):
            self.table.setItem(i, 0, QTableWidgetItem(str(i)))
            self.table.setItem(i, 1, QTableWidgetItem(hex(val)))
            self.table.setItem(i, 2, QTableWidgetItem(str(val)))
        self.status_label.setText(f"Прочитано {len(data_list)} байт")

    def read_eeprom_command(self):
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

        self.status_label.setText(f"Запрос чтения: {start}..{end}")
        self.eeprom_read_request.emit(start, count)

    def write_eeprom_command(self):
        try:
            address = int(self.write_address_input.text())
            if address < 0:
                raise ValueError
        except ValueError:
            self.status_label.setText("Ошибка: некорректный адрес записи")
            return

        raw_text = self.write_data_input.text().strip()
        if not raw_text:
            self.status_label.setText("Ошибка: не заданы данные для записи")
            return

        try:
            data = bytes(int(b, 16) for b in raw_text.split())
        except ValueError:
            self.status_label.setText("Ошибка: данные должны быть в hex, напр. '01 A0 FF'")
            return

        if not data:
            self.status_label.setText("Ошибка: пустые данные")
            return

        self.status_label.setText(f"Запись {len(data)} байт по адресу {address}")
        self.eeprom_write_request.emit(address, data)

    def save_table(self):
        rows = self.table.rowCount()
        cols = self.table.columnCount()
        result = [[self.table.item(r, c).text() if self.table.item(r, c) else "" for c in range(cols)] for r in range(rows)]
        print("EEPROM сохранены:", result)