from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import *

class EepromWindow(QWidget):
    send_eprom_command_signal = pyqtSignal(int, int, bytes)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Данные EEPROM")
        layout = QVBoxLayout(self)
        self.setLayout(layout)

        input_layout = QHBoxLayout()
        self.start_input = QLineEdit()
        self.end_input = QLineEdit()
        self.start_input.setPlaceholderText("Начальный индекс")
        self.end_input.setPlaceholderText("Конечный индекс")
        input_layout.addWidget(QLabel("От:"))
        input_layout.addWidget(self.start_input)
        input_layout.addWidget(QLabel("До:"))
        input_layout.addWidget(self.end_input)
        layout.addLayout(input_layout)

        buttons_layout = QHBoxLayout()
        self.generate_button = QPushButton("Прочитать")
        self.generate_button.clicked.connect(self.read_eeprom_command)
        buttons_layout.addWidget(self.generate_button)
        self.save_button = QPushButton("Сохранить")
        self.save_button.clicked.connect(self.save_table)
        buttons_layout.addWidget(self.save_button)
        layout.addLayout(buttons_layout)

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

    def read_eeprom_command(self):
        try:
            start = int(self.start_input.text())
            end = int(self.end_input.text())
            if start > end:
                raise ValueError
        except ValueError:
            self.start_input.setPlaceholderText("Ошибка")
            self.end_input.setPlaceholderText("Ошибка")
            return
        count = end - start + 1
        cmd_id = 0x11
        address = start
        num_bytes = bytes([count])
        self.send_eprom_command_signal.emit(cmd_id, address, num_bytes)

    def save_table(self):
        rows = self.table.rowCount()
        cols = self.table.columnCount()
        result = [[self.table.item(r, c).text() if self.table.item(r, c) else "" for c in range(cols)] for r in range(rows)]
        print("EEPROM сохранены:", result)

