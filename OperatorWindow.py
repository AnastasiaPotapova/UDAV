from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLineEdit, QPushButton


class OperatorWindow(QWidget):
    """
    Окно 'Настройки -> Добавить оператора' (см. ТЗ, п.2).
    Раньше эти поля были прямо на главном экране, теперь - отдельное окно.
    """
    operator_saved = pyqtSignal(str, str)  # operator, installation

    def __init__(self, operator: str = "", installation: str = ""):
        super().__init__()
        self.setWindowTitle("Добавить оператора")
        self.setFixedSize(420, 160)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.operator_edit = QLineEdit(operator)
        self.operator_edit.setPlaceholderText("Иванов Иван Иванович")

        self.installation_edit = QLineEdit(installation)
        self.installation_edit.setPlaceholderText("Вакуумная установка №1")

        form_layout.addRow("ФИО оператора:", self.operator_edit)
        form_layout.addRow("Название установки:", self.installation_edit)

        layout.addLayout(form_layout)

        self.save_btn = QPushButton("Сохранить")
        self.save_btn.clicked.connect(self._on_save)
        layout.addWidget(self.save_btn)

    def _on_save(self):
        operator = self.operator_edit.text().strip()
        installation = self.installation_edit.text().strip()
        if not operator or not installation:
            return
        self.operator_saved.emit(operator, installation)
        self.close()
