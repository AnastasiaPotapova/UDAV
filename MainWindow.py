import serial.tools.list_ports
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QStackedWidget, QVBoxLayout, QPushButton, QScrollArea, \
    QMessageBox, QLabel, QComboBox, QLineEdit, QFormLayout

from Engine import Engine
from GraphWindow import GraphPanel
from ModesManager import ModesManager
from ShematicWindow import SchematicWidget
from ProtocolEditorWindow import ProtocolEditorWindow
from EepromWindow import EepromWindow
from ConfigWindow import ConfigWindow
from LogWindow import LogWindow
from SoftwareInfoWindow import SoftwareInfoWindow
from LegendWindow import LegendWindow

# ------------------------------------------------------------------------------------------------
#                                  ОКНО НАСТРОЕК ПОДКЛЮЧЕНИЯ
# ------------------------------------------------------------------------------------------------
class ConnectSettingsWindow(QWidget):
    connect_signal = pyqtSignal(str, int, int)  # port, baudrate, timeout (ms)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Настройки подключения")
        self.setFixedSize(400, 200)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Порт:"))
        self.port_combo = QComboBox()
        layout.addWidget(self.port_combo)

        layout.addWidget(QLabel("Скорость:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "57600", "38400", "19200", "9600"])
        layout.addWidget(self.baud_combo)

        layout.addWidget(QLabel("Таймаут (мс):"))
        self.timeout_input = QLineEdit("1000")
        layout.addWidget(self.timeout_input)

        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Обновить порты")
        self.connect_btn = QPushButton("Подключиться")
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.connect_btn)
        layout.addLayout(btn_layout)

        # --- сигналы ---
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self.emit_connection)

        self.refresh_ports()

    def refresh_ports(self):
        """Обновляем список доступных COM-портов"""
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        if ports:
            for p in ports:
                self.port_combo.addItem(p.device)
        else:
            self.port_combo.addItem("Нет доступных портов")

    def emit_connection(self):
        """Вызывается при клике 'Подключиться' — отправляет сигнал с параметрами"""
        port = self.port_combo.currentText()
        baud = int(self.baud_combo.currentText())
        try:
            timeout = int(self.timeout_input.text())
        except ValueError:
            timeout = 1000  # ms

        # сигнал MainWindow/Engine, чтобы движок открыл порт
        self.connect_signal.emit(port, baud, timeout)
        self.close()


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine):
        super().__init__()
        self.setWindowTitle("SCADA UDAV")
        self.setGeometry(100, 100, 1280, 900)
        self.engine = engine  # ссылка на основной движок
        self.error_box_open = False
        self.connected = False

        self.init_ui()

        # --- подписка на события от движка ---
        self.engine.packet_received.connect(self.display_data)

    def init_ui(self):

        # ===== центральный виджет =====
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        self.work_control = QStackedWidget()

        # --- продвинутый режим ---
        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)

        self.valve_buttons = {}

        for name in ("V1", "V2", "V3", "V4", "V5", "V8"):
            btn = QPushButton(f"Открыть клапан {name}")
            btn.clicked.connect(lambda _, n=name: self._on_valve_click(n))
            control_layout.addWidget(btn)
            self.valve_buttons[name] = btn

        self.work_control.addWidget(control_panel)

        # --- базовый режим ---
        basic_panel = QWidget()
        basic_layout = QVBoxLayout(basic_panel)

        self.modes_manager = ModesManager(
            layout=basic_layout, engine=self.engine
        )


        self.work_control.addWidget(basic_panel)

        scroll = QScrollArea()
        scroll.setWidget(self.work_control)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(220)

        main_layout.addWidget(scroll)

        # ======================================================
        # 2 СТОЛБЕЦ — поля + схема
        # ======================================================
        middle_widget = QWidget()
        middle_layout = QVBoxLayout(middle_widget)

        # --- поля ввода ---
        form_layout = QFormLayout()

        self.operator_edit = QLineEdit()
        self.operator_edit.setPlaceholderText("Иванов Иван Иванович")

        self.installation_edit = QLineEdit()
        self.installation_edit.setPlaceholderText("Вакуумная установка №1")

        form_layout.addRow("ФИО оператора:", self.operator_edit)
        form_layout.addRow("Название установки:", self.installation_edit)

        # --- кнопка сохранить ---
        self.save_meta_btn = QPushButton("Сохранить")
        self.save_meta_btn.setEnabled(False)  # изначально неактивна

        form_layout.addRow(self.save_meta_btn)

        middle_layout.addLayout(form_layout)

        self.operator_edit.textChanged.connect(self._on_meta_changed)
        self.installation_edit.textChanged.connect(self._on_meta_changed)
        self.save_meta_btn.clicked.connect(self._save_meta)

        # --- схематика ---
        self.schematic = SchematicWidget()
        self.schematic.valve_command.connect(self._on_valve_click)

        middle_layout.addWidget(self.schematic, stretch=1)

        main_layout.addWidget(middle_widget, stretch=1)

        # ======================================================
        # 3 СТОЛБЕЦ — графики
        # ======================================================
        self.graph_panel = GraphPanel()
        main_layout.addWidget(self.graph_panel, stretch=1)

        # ======================================================
        # МЕНЮ
        # ======================================================
        menubar = self.menuBar()

        settings_menu = menubar.addMenu("Настройки")
        settings_menu.addAction("Подключение").triggered.connect(self.open_connect_settings)
        settings_menu.addAction("Редактировать конфигурацию").triggered.connect(self.ReadConfig)
        settings_menu.addAction("Редактировать протокол").triggered.connect(self.open_protocol_editor)

        mode_menu = menubar.addMenu("Режим работы")
        mode_menu.addAction("Автоматический").triggered.connect(
            lambda: self.work_control.setCurrentIndex(1)
        )
        mode_menu.addAction("Продвинутый").triggered.connect(
            lambda: self.work_control.setCurrentIndex(0)
        )

        eeprom_menu = menubar.addMenu("ЭСППЗУ")
        eeprom_menu.addAction("Прочитать").triggered.connect(self.ReadEeprom)
        eeprom_menu.addAction("Записать")

        logs_menu = menubar.addMenu("Логи")
        logs_menu.addAction("Открыть окно логов").triggered.connect(self.open_log_window)
        menubar.addMenu("Сгенерировать протокол поверки")

        info_menu = menubar.addMenu("Сведения")
        info_menu.addAction("Программное обеспечение").triggered.connect(self.open_software_info)
        info_menu.addAction("Условные обозначения").triggered.connect(self.open_legend)

    def _save_meta(self):
        operator = self.operator_edit.text().strip()
        installation = self.installation_edit.text().strip()

        if not operator or not installation:
            # можно заменить на QMessageBox, если хочешь строго
            return

        # ===== отправка в Engine =====
        self.engine.set_operator_info(
            operator=operator,
            installation=installation
        )

        # ===== блокируем кнопку =====
        self.save_meta_btn.setEnabled(False)

    def _on_meta_changed(self):
        self.save_meta_btn.setEnabled(True)

    # ---------- команды на клапаны ----------

    def _on_valve_click(self, name, _=None):
        schematic = self.schematic.items
        if name in schematic:
            item = schematic[name]
            item.status = "waiting"
            item.update_color()

        self._update_valve_button(name, "waiting")
        self.engine.request_state_change(name)

    def _update_valve_button(self, name: str, status: str):
        """Обновляет текст и активность кнопки клапана по статусу (closed/waiting/open)"""
        btn = self.valve_buttons.get(name)
        if not btn:
            return

        if status == "closed":
            btn.setText(f"Открыть клапан {name}")
            btn.setEnabled(True)
        elif status == "waiting":
            btn.setText(f"Отправлено... {name}")
            btn.setEnabled(False)
        elif status == "open":
            btn.setText(f"Закрыть клапан {name}")
            btn.setEnabled(True)

    # ---------- подключение ----------

    def open_connect_settings(self):
        self.conn_win = ConnectSettingsWindow()
        self.conn_win.connect_signal.connect(self.start_serial)
        self.conn_win.show()

    def start_serial(self, port, baud, timeout):
        self.engine.serial.port_name = port
        self.engine.serial.baudrate = baud
        self.engine.serial.timeout = timeout
        self.engine.open_serial()
        self.update_connection_status(True)

    def stop_serial(self):
        self.engine.close_serial()
        self.update_connection_status(False)

    def update_connection_status(self, connected: bool):
        self.connected = connected
        postfix = " (подключено)" if connected else " (нет подключения)"
        self.setWindowTitle("SCADA NIIM" + postfix)


    # ---------- отображение данных ----------
    def display_data(self, data: dict):
        if data["__packet__"] == "exchange_packet":
            self.graph_panel.update_plots([
                data.get("mida_pressure"),
                data.get("magdischarge_pressure"),
                data.get("thermal_pressure")
            ])
            self.update_schematic(data)

    def apply_valve_state(self, name: str, is_open: bool):
        """Единая точка применения реального состояния от Engine к схеме и кнопке"""
        status = "open" if is_open else "closed"

        schematic = self.schematic.items
        if name in schematic:
            schematic[name].apply_system_state(is_open)

        self._update_valve_button(name, status)

    def update_schematic(self, data: dict):
        if "forvacuum_state" in data:
            self.apply_valve_state("NI", bool(data["forvacuum_state"]))

        if "tmn_state" in data:
            self.apply_valve_state("NR", bool(data["tmn_state"]))

        if "du16" in data:
            for k, v in data["du16"].items():
                self.apply_valve_state(k, bool(v))

        if "du63" in data:
            self.apply_valve_state("V2", bool(data["du63"]))

        if "electro_valves" in data:
            for k, v in data["electro_valves"].items():
                self.apply_valve_state(k, bool(v))

    def display_error(self, msg: str):
        if not self.error_box_open:
            self.error_box_open = True
            box = QMessageBox(self)
            box.setWindowTitle("Ошибка связи")
            box.setText(msg)
            box.setIcon(QMessageBox.Critical)
            box.setStandardButtons(QMessageBox.Ok)
            box.buttonClicked.connect(lambda _: setattr(self, 'error_box_open', False))
            box.show()

    # ----------  окна ----------
    def open_protocol_editor(self):
        self.protocol_window = ProtocolEditorWindow()
        self.protocol_window.show()

    def ReadEeprom(self):
        self.w = EepromWindow()
        self.w.eeprom_read_request.connect(self.engine.eeprom_read)
        self.w.eeprom_write_request.connect(self.engine.eeprom_write)
        self.engine.eeprom_data_received.connect(self.w.handle_data)
        self.w.show()

    def ReadConfig(self):
        self.w2 = ConfigWindow()
        self.w2.show()

    def open_log_window(self):
        self.log_window = LogWindow()
        self.log_window.show()

    def open_software_info(self):
        self.software_info_window = SoftwareInfoWindow()
        self.software_info_window.show()

    def open_legend(self):
        self.legend_window = LegendWindow()
        self.legend_window.show()