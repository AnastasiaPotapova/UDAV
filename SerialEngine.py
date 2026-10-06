import threading
import queue
import serial
import time
from typing import Optional
from logger_setup import app_logger

# Фиксированные параметры подключения
FIXED_BAUDRATE = 9600
FIXED_TIMEOUT_MS = 2000                     # мс
FIXED_TIMEOUT_S = FIXED_TIMEOUT_MS / 1000   # pyserial принимает секунды


class SerialEngine:
    """Управление последовательным портом с буферной отправкой и чтением"""

    def __init__(self, protocol_engine=None):
        self.port_name: Optional[str] = None
        self.baudrate: int = FIXED_BAUDRATE
        self.timeout: float = FIXED_TIMEOUT_S  # секунды

        self.ser: Optional[serial.Serial] = None
        self.send_queue = queue.Queue()
        self.running = False
        self._lock = threading.Lock()
        self.protocol = protocol_engine

        self._threads_started = False

    # --- настройки порта ---
    def set_port_settings(self, port: str, baudrate: int = None, timeout: float = None):
        """Устанавливаем порт. Скорость и таймаут всегда фиксированные
        (9600 бод, 2000 мс), переданные baudrate/timeout игнорируются."""
        self.port_name = port
        self.baudrate = FIXED_BAUDRATE
        self.timeout = FIXED_TIMEOUT_S
        print(f"[INFO] Настройки порта установлены: {port}, {FIXED_BAUDRATE}bps, timeout={FIXED_TIMEOUT_MS}ms")

    # --- управление портом ---
    def open_port(self):
        if not self.port_name:
            raise RuntimeError("Сначала нужно установить настройки порта через set_port_settings()")
        if self.ser and self.ser.is_open:
            app_logger.info(f"Порт {self.port_name} уже открыт")
            return

        # на случай прямой записи в атрибуты снаружи
        self.baudrate = FIXED_BAUDRATE
        self.timeout = FIXED_TIMEOUT_S

        self.ser = serial.Serial(self.port_name, self.baudrate,
                                 timeout=self.timeout, write_timeout=self.timeout)
        self.running = True
        self._start_threads()
        app_logger.info(f"Порт {self.port_name} открыт, скорость {self.baudrate}, таймаут {FIXED_TIMEOUT_MS} мс")

    def close_port(self):
        self.running = False
        t = getattr(self, "_thread", None)
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=self.timeout + 0.5)
        self._thread = None
        self._threads_started = False
        if self.ser and self.ser.is_open:
            self.ser.close()
            app_logger.info(f"Порт {self.port_name} закрыт")

    def _serial_thread(self):
        while self.running:
            try:
                if not self.send_queue.empty() and self.ser and self.ser.is_open:
                    msg = self.send_queue.get()
                    with self._lock:
                        self.ser.write(msg)
                    app_logger.debug(f"TX: {msg.hex()}")

                if self.ser and self.ser.is_open:
                    # читаем только уже пришедшее: при таймауте 2 с read(64) ждал бы
                    # все 2 с (пакет 32 байта) и задерживал бы и разбор, и отправку
                    waiting = self.ser.in_waiting
                    if waiting:
                        data = self.ser.read(waiting)
                        if data:
                            self._feed_protocol(data)

                time.sleep(0.01)
            except Exception as e:
                app_logger.error(f"Ошибка последовательного порта: {e}")
                time.sleep(0.2)

    # --- отправка данных ---
    def send(self, data: bytes):
        """Кладём данные в очередь на отправку"""
        app_logger.debug(f"TX queued: {data.hex()}")
        self.send_queue.put(data)

    # --- внутренние потоки ---
    def _start_threads(self):
        if self._threads_started:
            return
        self._thread = threading.Thread(target=self._serial_thread, daemon=True)
        self._thread.start()
        self._threads_started = True

    def _feed_protocol(self, data: bytes):
        if self.protocol:
            packets = self.protocol.feed(data)
            for pkt in packets:
                print(f"[PKT PARSED] {pkt}")
        else:
            print(f"[RX RAW] {data.hex()}")
