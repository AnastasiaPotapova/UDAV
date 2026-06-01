from PyQt5.QtWidgets import *

class ConfigWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Редактирование конфигурации")
        self.setFixedSize(400, 300)
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Параметр", "Значение", ""])
        layout.addWidget(self.table)

        for _ in range(3):
            self.add_row()

        self.add_button = QPushButton("Добавить строку")
        self.add_button.clicked.connect(self.add_row)
        layout.addWidget(self.add_button)
        self.save_button = QPushButton("Сохранить")
        layout.addWidget(self.save_button)

    def add_row(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(""))
        self.table.setItem(r, 1, QTableWidgetItem(""))
        btn = QPushButton("🗙")
        btn.setStyleSheet("color:red; font-weight:bold;")
        btn.clicked.connect(lambda _, row=r: self.delete_row(row))
        self.table.setCellWidget(r, 2, btn)

    def delete_row(self, row):
        self.table.removeRow(row)