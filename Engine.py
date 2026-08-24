from PyQt5.QtCore import QObject, pyqtSignal, QTimer
import threading
import time

from ProtocolEngine import ProtocolEngine
from SerialEngine import SerialEngine
from logger_setup import app_logger, controller_logger
from resource_path import resource_path

# Engine

class Engine(QObject):
    packet_received = pyqtSignal(dict)
    eeprom_data_received = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.protocol = ProtocolEngine(resource_path("protocol.json"))
        self.serial = SerialEngine(protocol_engine=self.protocol)

        self.serial._feed_protocol = self._feed_protocol
        self.system_status = {
            "NI": 0, "NR": 0,
            "V1": 0, "V2": 0, "V3": 0, "V4": 0,
            "V5": 0, "V6": 0, "V7": 0, "V8": 0
        }

        # последние показания датчиков (для сценариев автоматического режима)
        self.last_data = {}

        self.DU16_VALVES = ["V1", "V3", "V6", "V7"]
        self.ELECTRO_VALVES = ["V4", "V5", "V8"]

        self.CONTROL_MAP = {
            # Насосы
            "NI": {
                "cmd": "FORVACUUM_CONTROL",
                "cmd_id": 0x02
            },
            "NR": {
                "cmd": "TMN_CONTROL",
                "cmd_id": 0x03
            },

            # Датчик (особый случай, не on/off)
            "P2": {
                "cmd": "MIDA_UNITS",
                "cmd_id": 0x04
            },

            # Клапаны DU16
            "V1": {
                "cmd": "DU16_CONTROL",
                "cmd_id": 0x06
            },
            "V3": {
                "cmd": "DU16_CONTROL",
                "cmd_id": 0x06
            },
            "V6": {
                "cmd": "DU16_CONTROL",
                "cmd_id": 0x06
            },
            "V7": {
                "cmd": "DU16_CONTROL",
                "cmd_id": 0x06
            },

            # Клапан DU63
            "V2": {
                "cmd": "DU63_CONTROL",
                "cmd_id": 0x07
            },

            # Электромагнитные клапаны
            "V4": {
                "cmd": "ELECTRO_VALVE_CONTROL",
                "cmd_id": 0x08
            },
            "V5": {
                "cmd": "ELECTRO_VALVE_CONTROL",
                "cmd_id": 0x08
            },
            "V8": {
                "cmd": "ELECTRO_VALVE_CONTROL",
                "cmd_id": 0x08
            }
        }

        # расшифровка кодов ошибок для контроллерного лога
        self.ERROR_CODES = {
            "0x01": "UNKNOWN_COMMAND",
            "0x02": "INVALID_LENGTH",
            "0x03": "INVALID_ARGUMENT",
            "0x04": "INVALID_STATE",
            "0x05": "RS232_ERROR",
            "0x06": "RS485_ERROR",
            "0x07": "DEVICE_CONTROL_ERROR",
            "0x08": "EEPROM_ERROR",
        }

        self.operator = None
        self.installation = None
        app_logger.info("Engine инициализирован")

    def _feed_protocol(self, data: bytes):
        controller_logger.debug(f"RX RAW: {data.hex()}")

        packets = self.protocol.feed(data)
        for pkt in packets:
            app_logger.debug(f"Распакован пакет: {pkt}")
            self._log_controller_packet(pkt)

            if pkt.get("__packet__") == "eprom_read_response":
                raw_bytes = pkt.get("data", b"")
                app_logger.info(f"EEPROM прочитано {len(raw_bytes)} байт")
                self.eeprom_data_received.emit(list(raw_bytes))
                continue

            if pkt.get("__packet__") == "exchange_packet":
                self._update_last_data(pkt)

            self.packet_received.emit(pkt)

    def _update_last_data(self, pkt: dict):
        """Сохраняем последние показания датчиков для сценариев автоматического режима"""
        if "mida_pressure" in pkt:
            self.last_data["MIDA"] = pkt["mida_pressure"]
        if "magdischarge_pressure" in pkt:
            self.last_data["Magdischarge"] = pkt["magdischarge_pressure"]
        if "thermal_pressure" in pkt:
            self.last_data["ThermalIndicator"] = pkt["thermal_pressure"]

    def set_element_state(self, name: str, state: int):
        app_logger.info(f"set_element_state({name}, {state})")
        self._send_element_command(name, state)

    def _log_controller_packet(self, pkt: dict):
        """Пишет в лог контроллера: OK или расшифровку ошибки"""
        name = pkt.get("__packet__")
        if name == "error_packet":
            code = pkt.get("error_code")
            decoded = self.ERROR_CODES.get(code, code)
            controller_logger.error(f"Ошибка контроллера: {decoded} (код: {code})")
        else:
            controller_logger.info("OK")

    def set_serial_settings(self, port: str, baud: int, timeout: float):
        app_logger.info(f"set_serial_settings(port={port}, baud={baud}, timeout={timeout})")
        self.serial.set_port_settings(port, baud, timeout)

    def open_serial(self):
        app_logger.info("open_serial()")
        self.serial.open_port()

    def close_serial(self):
        app_logger.info("close_serial()")
        self.serial.close_port()

    def request_state_change(self, name: str):
        app_logger.info(f"request_state_change({name})")
        if name not in self.system_status:
            app_logger.warning(f"Неизвестный элемент: {name}")
            return

        current = self.system_status[name]
        target = 0 if current else 1
        self._send_element_command(name, target)

    def _build_bitfield(self, valves: list[str]) -> int:
        value = 0
        for i, name in enumerate(valves):
            if self.system_status.get(name, 0):
                value |= 1 << i
        return value

    def _send_element_command(self, name: str, target_state: int):
        if name not in self.system_status:
            app_logger.warning(f"Неизвестный элемент: {name}")
            return

        current_state = self.system_status[name]
        if current_state == target_state:
            app_logger.info(f"{name} уже в состоянии {target_state}")
            return

        app_logger.info(f"_send_element_command: {name}: {current_state} → {target_state}")
        self.system_status[name] = target_state

        if name == "NI":
            self.send_control("FORVACUUM_CONTROL", target_state)
            return
        if name == "NR":
            self.send_control("TMN_CONTROL", target_state)
            return
        if name in ("V1", "V3", "V6", "V7"):
            payload = self._build_bitfield(self.DU16_VALVES)
            self.send_control("DU16_CONTROL", payload)
            return
        if name == "V2":
            self.send_control("DU63_CONTROL", target_state)
            return
        if name in ("V4", "V5", "V8"):
            payload = self._build_bitfield(self.ELECTRO_VALVES)
            self.send_control("ELECTRO_VALVE_CONTROL", payload)
            return

        app_logger.warning(f"Нет маппинга команды для {name}")

    def send_control(self, cmd_name, data):
        app_logger.debug(f"send_control({cmd_name}, {data})")
        pkt_bytes = self.protocol.build_control(cmd_name, data)
        self.serial.send(pkt_bytes)

    def send_raw(self, data: bytes):
        app_logger.debug(f"send_raw({data.hex()})")
        self.serial.send(data)

    def set_operator_info(self, operator: str, installation: str):
        app_logger.info(f"set_operator_info(operator={operator}, installation={installation})")
        self.operator = operator
        self.installation = installation

    def eeprom_read(self, address: int, num_bytes: int):
        app_logger.info(f"eeprom_read(address={address}, num_bytes={num_bytes})")
        pkt_bytes = self.protocol.build_eprom_read(address, num_bytes)
        self.serial.send(pkt_bytes)

    def eeprom_write(self, address: int, data: bytes):
        app_logger.info(f"eeprom_write(address={address}, data={data.hex()})")
        pkt_bytes = self.protocol.build_eprom_write(address, data)
        self.serial.send(pkt_bytes)