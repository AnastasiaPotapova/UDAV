from PyQt5.QtCore import QObject, pyqtSignal, QTimer
import threading
import time

from ProtocolEngine import ProtocolEngine
from SerialEngine import SerialEngine

# Engine

class Engine(QObject):
    packet_received = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.protocol = ProtocolEngine("protocol.json")
        self.serial = SerialEngine(protocol_engine=self.protocol)

        # Переопределяем callback для пакетов
        self.serial._feed_protocol = self._feed_protocol
        self.system_status = {
            "NI": 0, "NR": 0,
            "V1": 0, "V2": 0, "V3": 0, "V4": 0,
            "V5": 0, "V6": 0, "V7": 0, "V8": 0
        }

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

        #Информация для протокола
        self.operator = None
        self.installation = None

    def _feed_protocol(self, data: bytes):
        packets = self.protocol.feed(data)
        for pkt in packets:
            #print(f"[ENGINE] New packet: {pkt}")
            print(pkt['electro_valves'])
            self.packet_received.emit(pkt)

    def set_serial_settings(self, port: str, baud: int, timeout: float):
        self.serial.set_port_settings(port, baud, timeout)

    def open_serial(self):
        self.serial.open_port()

    def close_serial(self):
        self.serial.close_port()

    def request_state_change(self, name: str):
        if name not in self.system_status:
            print(f"[ENGINE] Unknown element: {name}")
            return

        current = self.system_status[name]
        target = 0 if current else 1  # toggle

        self._send_element_command(name, target)

    def _build_bitfield(self, valves: list[str]) -> int:
        value = 0
        for i, name in enumerate(valves):
            if self.system_status.get(name, 0):
                value |= 1 << i
        return value

    def _send_element_command(self, name: str, target_state: int):
        if name not in self.system_status:
            print(f"[ENGINE] Unknown element: {name}")
            return

        current_state = self.system_status[name]
        if current_state == target_state:
            print(f"[ENGINE] {name} already in state {target_state}")
            return

        print(f"[ENGINE] {name}: {current_state} → {target_state}")

        # обновляем локальное состояние
        self.system_status[name] = target_state

        # -------- НАСОСЫ --------
        if name == "NI":
            self.send_control("FORVACUUM_CONTROL", target_state)
            return

        if name == "NR":
            self.send_control("TMN_CONTROL", target_state)
            return

        # -------- DU16 --------
        if name in ("V1", "V3", "V6", "V7"):
            payload = self._build_bitfield(self.DU16_VALVES)
            self.send_control("DU16_CONTROL", payload)
            return

        # -------- DU63 --------
        if name == "V2":
            self.send_control("DU63_CONTROL", target_state)
            return

        # -------- ELECTRO --------
        if name in ("V4", "V5", "V8"):
            payload = self._build_bitfield(self.ELECTRO_VALVES)
            self.send_control("ELECTRO_VALVE_CONTROL", payload)
            return

        print(f"[ENGINE] No command mapping for {name}")

    def send_control(self, cmd_name, data):
        pkt_bytes = self.protocol.build_control(cmd_name, data)
        self.serial.send(pkt_bytes)

    def send_raw(self, data: bytes):
        self.serial.send(data)

    def set_operator_info(self, operator: str, installation: str):
        self.operator = operator
        self.installation = installation