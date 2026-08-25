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
    eeprom_data_received = pyqtSignal(dict)

    # Группы клапанов, состояние которых кодируется одним битовым полем
    DU16_VALVES = ["V1", "V3", "V6", "V7"]
    ELECTRO_VALVES = ["V4", "V5", "V8"]

    def __init__(self):
        super().__init__()
        self.protocol = ProtocolEngine(resource_path("protocol.json"))
        self.serial = SerialEngine(protocol_engine=self.protocol)

        # Переопределяем callback для пакетов
        self.serial._feed_protocol = self._feed_protocol
        self.system_status = {
            "NI": 0, "NR": 0,
            "V1": 0, "V2": 0, "V3": 0, "V4": 0,
            "V5": 0, "V6": 0, "V7": 0, "V8": 0,
            "VF": 0
        }

        #Информация для протокола
        self.operator = None
        self.installation = None

        # Последний разобранный пакет опроса (для ModesManager: CHECK/WAIT/SAVE)
        self.last_data = {}

    def _feed_protocol(self, data: bytes):
        packets = self.protocol.feed(data)
        for pkt in packets:
            #print(f"[ENGINE] New packet: {pkt}")
            if pkt.get("__packet__") == "exchange_packet":
                self.last_data = pkt
            print(pkt.get('electro_valves'))
            self.packet_received.emit(pkt)

    def set_serial_settings(self, port: str, baud: int, timeout: float):
        self.serial.set_port_settings(port, baud, timeout)

    def open_serial(self):
        self.serial.open_port()

    def close_serial(self):
        self.serial.close_port()

    # ------------------------------------------------------------------
    # Переключение по клику из UI (тумблер: если открыт — закрыть, и наоборот)
    # ------------------------------------------------------------------
    def request_state_change(self, name: str):
        if name not in self.system_status:
            print(f"[ENGINE] Unknown element: {name}")
            return

        current = self.system_status[name]
        target = 0 if current else 1  # toggle

        self._send_element_command(name, target)

    # ------------------------------------------------------------------
    # Явная установка состояния (используется ModesManager и UI)
    # ------------------------------------------------------------------
    def set_valve(self, name: str, is_open: bool):
        """Явно установить состояние клапана (OPEN/CLOSE)."""
        self._send_element_command(name, 1 if is_open else 0)

    def set_device(self, name: str, is_on: bool):
        """Явно установить состояние насоса/устройства (ON/OFF)."""
        self._send_element_command(name, 1 if is_on else 0)

    def set_pressure(self, pressure_pa: float):
        """Уставка давления через клапан VF (cmd 0x09, payload float32)."""
        self.send_control("SET_PRESSURE", float(pressure_pa))

    def set_mida_units(self, torr: bool):
        """Смена единиц измерения датчика P2 (cmd 0x04): 0 - Па, 1 - Торр."""
        self.send_control("MIDA_UNITS", 1 if torr else 0)

    # ------------------------------------------------------------------
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

        # обновляем локальное состояние ДО построения битового поля,
        # чтобы битовое поле группы учитывало новое состояние этого клапана
        self.system_status[name] = target_state

        # -------- НАСОСЫ --------
        if name == "NI":
            self.send_control("FORVACUUM_CONTROL", target_state)
            return

        if name == "NR":
            self.send_control("TMN_CONTROL", target_state)
            return

        # -------- DU16 (битовое поле по всей группе сразу) --------
        if name in self.DU16_VALVES:
            payload = self._build_bitfield(self.DU16_VALVES)
            self.send_control("DU16_CONTROL", payload)
            return

        # -------- DU63 (одиночный клапан, простой uint8) --------
        if name == "V2":
            self.send_control("DU63_CONTROL", target_state)
            return

        # -------- ELECTRO (битовое поле по всей группе сразу) --------
        if name in self.ELECTRO_VALVES:
            payload = self._build_bitfield(self.ELECTRO_VALVES)
            self.send_control("ELECTRO_VALVE_CONTROL", payload)
            return

        # -------- VF (пропорциональный клапан, работает через SET_PRESSURE) --------
        # ВНИМАНИЕ: в протоколе нет отдельной команды ON/OFF для VF — регулировка
        # идёт через 0x09 (SET_PRESSURE, payload float32). Клик по клапану на схеме
        # трактуется как "включить/выключить регулирование давления" условным
        # значением 1.0/0.0 — заменить на реальную уставку, когда появится формула.
        if name == "VF":
            self.set_pressure(1.0 if target_state else 0.0)
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

    # ------------------------------------------------------------------
    # EEPROM
    # ------------------------------------------------------------------

    def eeprom_read(self, address: int, num_bytes: int):
        app_logger.info(f"eeprom_read(address={address}, num_bytes={num_bytes})")
        pkt_bytes = self.protocol.build_eprom_read(address, num_bytes)
        self.serial.send(pkt_bytes)

    def eeprom_write(self, address: int, data: bytes):
        app_logger.info(f"eeprom_write(address={address}, data={data.hex()})")
        pkt_bytes = self.protocol.build_eprom_write(address, data)
        self.serial.send(pkt_bytes)

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
                continue  # не пробрасываем в общий packet_received

            self.packet_received.emit(pkt)


