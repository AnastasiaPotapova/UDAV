from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel

# Данные о встроенном ПО платы контроллера.
# Обновлять при каждой перепрошивке платы.
FIRMWARE_NAME = "УДАВ-Контроллер"
FIRMWARE_VERSION = "1.0.0"


class SoftwareInfoWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Программное обеспечение")
        self.setFixedSize(400, 150)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.addRow("Наименование ПО:", QLabel(FIRMWARE_NAME))
        form.addRow("Версия ПО:", QLabel(FIRMWARE_VERSION))
        layout.addLayout(form)

        note = QLabel(
            "Указана версия внутреннего программного обеспечения,\n"
            "записанного в плату контроллера."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

