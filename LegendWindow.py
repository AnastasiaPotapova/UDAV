from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView

LEGEND_DATA = [
    ("CV1", "Камера измерительная"),
    ("NI", "Насос вакуумный НВР-4,5Д"),
    ("NR", "Насос высоковакуумный турбомолекулярный ТМГН-51М"),
    ("P1", "Датчик давления МИДА-ДА-15"),
    ("P2", "Датчик давления широкодиапазонный двухпортовый МИДА-15"),
    ("P3", "Вакуумметр инверсно-магнетронный СЕНСОР-МАГНЕТРОН"),
    ("V1, V3", "Клапан электромагнитный KV-V-A-KF-16-AL-BE-FKM-M-24DC"),
    ("V2", "Клапан вакуумный электромеханический с приводом КВЭ-63"),
    ("V4, V5, V8", "Клапан вакуумный угловой с электромеханическим приводом KV-V-A-KF-16-AL-BE-FKM-Е-24DC"),
    ("V6, V7", "Клапан вакуумный сильфонный угловой KF16"),
    ("VF", "Клапан пропорциональный"),
]


class LegendWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Условные обозначения")
        self.resize(650, 400)

        layout = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Обозначение", "Расшифровка"])
        self.table.setRowCount(len(LEGEND_DATA))
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        for row, (symbol, description) in enumerate(LEGEND_DATA):
            symbol_item = QTableWidgetItem(symbol)
            desc_item = QTableWidgetItem(description)
            self.table.setItem(row, 0, symbol_item)
            self.table.setItem(row, 1, desc_item)

        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.resizeRowsToContents()

        layout.addWidget(self.table)