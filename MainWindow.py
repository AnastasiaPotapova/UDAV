import serial.tools.list_ports
from PyQt5.QtCore import pyqtSignal, QTimer, Qt
from PyQt5.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QScrollArea, \
    QMessageBox, QLabel, QComboBox, QLineEdit, QFrame

from Engine import Engine
from GraphWindow import GraphPanel
from LegendWindow import LegendWindow
from LogWindow import LogWindow
from ModesManager import ModesManager
from OperatorWindow import OperatorWindow
from StatusIndicator import StatusIndicator
from ShematicWindow import SchematicWidget
from ProtocolEditorWindow import ProtocolEditorWindow
from EepromWindow import EepromWindow
from ConfigWindow import ConfigWindow
from SoftwareInfoWindow import SoftwareInfoWindow
from pressure_format import format_p1, format_p2, format_p3, format_pstat


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
    packet_received = pyqtSignal(dict)
    eeprom_data_received = pyqtSignal(list)

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

        # самодиагностика: если билд UI и подписки прошли без исключений -
        # считаем ПО готовым к работе (см. StatusIndicator, ТЗ п.6)
        QTimer.singleShot(600, lambda: self.status_indicator.set_state("ok"))

    def init_ui(self):

        # ===== центральный виджет =====
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)

        main_layout = QHBoxLayout()
        root_layout.addLayout(main_layout, stretch=1)

        # ======================================================
        # 1 СТОЛБЕЦ — готовые команды (сценарии из modes.txt)
        # ======================================================
        # Управление отдельными клапанами/насосами теперь ведётся только
        # прямым нажатием на схему; здесь остаются только уже собранные
        # (составные) команды - см. ТЗ п.1.
        commands_panel = QWidget()
        commands_layout = QVBoxLayout(commands_panel)

        self.modes_manager = ModesManager(
            layout=commands_layout,
            engine=self.engine
        )

        scroll = QScrollArea()
        scroll.setWidget(commands_panel)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(220)

        main_layout.addWidget(scroll)

        # ======================================================
        # 2 СТОЛБЕЦ — индикатор + схема
        # ======================================================
        middle_widget = QWidget()
        middle_layout = QVBoxLayout(middle_widget)

        # --- индикатор самодиагностики (ТЗ п.6) ---
        indicator_row = QHBoxLayout()
        indicator_row.addStretch()
        self.status_indicator = StatusIndicator()
        self.status_indicator.clicked.connect(self.open_log_window)
        indicator_row.addWidget(self.status_indicator)
        middle_layout.addLayout(indicator_row)

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
        # НИЖНЯЯ ПАНЕЛЬ — текущие значения измерений (ТЗ п.3)
        # ======================================================
        root_layout.addLayout(self._build_values_bar())

        # ======================================================
        # МЕНЮ
        # ======================================================
        menubar = self.menuBar()

        settings_menu = menubar.addMenu("Настройки")
        settings_menu.addAction("Подключение").triggered.connect(self.open_connect_settings)
        settings_menu.addAction("Добавить оператора").triggered.connect(self.open_operator_window)
        settings_menu.addAction("Редактировать конфигурацию").triggered.connect(self.ReadConfig)
        settings_menu.addAction("Редактировать протокол").triggered.connect(self.open_protocol_editor)

        eeprom_menu = menubar.addMenu("ЭСППЗУ")
        eeprom_menu.addAction("Прочитать").triggered.connect(self.ReadEeprom)
        eeprom_menu.addAction("Записать")

        logs_menu = menubar.addMenu("Журнал ошибок")
        logs_menu.addAction("Открыть").triggered.connect(self.open_log_window)

        info_menu = menubar.addMenu("Сведения")
        info_menu.addAction("Программное обеспечение").triggered.connect(self.open_software_info)
        info_menu.addAction("Условные обозначения").triggered.connect(self.open_legend)

    def _build_values_bar(self):
        """Строка с текущими значениями Р1, Р2, Р3, Р стат. внизу экрана (ТЗ п.3)."""
        bar_layout = QHBoxLayout()

        self.value_labels = {}
        specs = [
            ("P1", "Р1"),
            ("P2", "Р2"),
            ("P3", "Р3"),
            ("PSTAT", "Р стат."),
        ]
        for key, caption in specs:
            box = QFrame()
            box.setFrameShape(QFrame.StyledPanel)
            box_layout = QHBoxLayout(box)

            title = QLabel(f"{caption}:")
            title.setStyleSheet("font-weight: bold;")
            value = QLabel("—")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            box_layout.addWidget(title)
            box_layout.addWidget(value)

            self.value_labels[key] = value
            bar_layout.addWidget(box)

        return bar_layout

    def _update_values_bar(self, data: dict):
        """Обновляет нижнюю панель значений по данным обменного пакета."""
        self.value_labels["P1"].setText(format_p1(data.get("mida_pressure")))
        self.value_labels["P2"].setText(format_p2(data.get("magdischarge_pressure")))
        self.value_labels["P3"].setText(format_p3(data.get("thermal_pressure")))
        self.value_labels["PSTAT"].setText(format_pstat(self.engine.static_pressure))

    def ReadEeprom(self):
        self.w = EepromWindow()
        self.w.eeprom_read_request.connect(self.engine.eeprom_read)
        self.w.eeprom_write_request.connect(self.engine.eeprom_write)
        self.engine.eeprom_data_received.connect(self.w.handle_data)
        self.w.show()

    # ---------- оператор (ТЗ п.2) ----------
    def open_operator_window(self):
        self.operator_window = OperatorWindow(
            operator=self.engine.operator or "",
            installation=self.engine.installation or "",
        )
        self.operator_window.operator_saved.connect(self._save_meta)
        self.operator_window.show()

    def _save_meta(self, operator: str, installation: str):
        self.engine.set_operator_info(operator=operator, installation=installation)

    # ---------- команды на клапаны ----------

    def _on_valve_click(self, name, _=None):
        schematic = self.schematic.items
        if name in schematic:
            item = schematic[name]
            item.status = "waiting"
            item.update_color()

        self.engine.request_state_change(name)

    # ---------- подключение ----------

    def open_connect_settings(self):
        self.conn_win = ConnectSettingsWindow()
        self.conn_win.connect_signal.connect(self.start_serial)
        self.conn_win.show()

    def start_serial(self, port, baud, timeout):
        try:
            self.engine.serial.port_name = port
            self.engine.serial.baudrate = baud
            self.engine.serial.timeout = timeout
            self.engine.open_serial()
        except Exception as e:
            self.status_indicator.set_state("error")
            self.display_error(f"Не удалось открыть порт {port}: {e}")
            self.update_connection_status(False)
            return
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
        packet_name = data.get("__packet__")

        if packet_name == "error_packet":
            self.status_indicator.set_state("error")
            self.display_error(
                f"Ошибка {data.get('error_code')} на команду {data.get('cmd_id')}"
            )
            return

        if packet_name == "exchange_packet":
            # обновляем графики
            self.graph_panel.update_plots([
                data.get("mida_pressure"),
                data.get("magdischarge_pressure"),
                data.get("thermal_pressure")
            ])
            # обновляем схему
            self.update_schematic(data)
            # обновляем нижнюю панель значений
            self._update_values_bar(data)

    def apply_valve_state(self, name: str, is_open: bool):
        """Единая точка применения реального состояния от Engine к схеме"""
        # синхронизируем локальное состояние Engine с реальным состоянием устройства
        if name in self.engine.system_status:
            self.engine.system_status[name] = 1 if is_open else 0

        schematic = self.schematic.items
        if name in schematic:
            schematic[name].apply_system_state(is_open)

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

    def ReadConfig(self):
        self.w2 = ConfigWindow()
        self.w2.show()

    def open_software_info(self):
        self.software_info_window = SoftwareInfoWindow()
        self.software_info_window.show()

    def open_legend(self):
        self.legend_window = LegendWindow()
        self.legend_window.show()

    def open_log_window(self):
        self.log_window = LogWindow()
        self.log_window.show()
