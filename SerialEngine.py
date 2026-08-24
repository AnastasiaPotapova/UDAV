import threading
import queue
import serial
import time
from typing import Optional
from logger_setup import app_logger

class SerialEngine:
    """Управление последовательным портом с буферной отправкой и чтением"""

    def __init__(self, protocol_engine=None):
        self.port_name: Optional[str] = None
        self.baudrate: int = 115200
        self.timeout: float = 0.1

        self.ser: Optional[serial.Serial] = None
        self.send_queue = queue.Queue()
        self.running = False
        self._lock = threading.Lock()
        self.protocol = protocol_engine

        self._threads_started = False

    # --- настройки порта ---
    def set_port_settings(self, port: str, baudrate: int = 115200, timeout: float = 0.1):
        """Устанавливаем параметры порта перед открытием"""
        self.port_name = port
        self.baudrate = baudrate
        self.timeout = timeout
        print(f"[INFO] Настройки порта установлены: {port}, {baudrate}bps, timeout={timeout}s")

    # --- управление портом ---
    def open_port(self):
        if not self.port_name:
            raise RuntimeError("Сначала нужно установить настройки порта через set_port_settings()")
        if self.ser and self.ser.is_open:
            app_logger.info(f"Порт {self.port_name} уже открыт")
            return

        self.ser = serial.Serial(self.port_name, self.baudrate, timeout=self.timeout)
        self.running = True
        self._start_threads()
        app_logger.info(f"Порт {self.port_name} открыт, скорость {self.baudrate}")

    def close_port(self):
        self.running = False
        time.sleep(0.05)
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
                    data = self.ser.read(64)
                    if data:
                        self._feed_protocol(data)

                time.sleep(0.01)
            except Exception as e:
                app_logger.error(f"Ошибка последовательного порта: {e}")

    # --- отправка данных ---
    def send(self, data: bytes):
        """Кладём данные в очередь на отправку"""
        print(f"[RX RAW] {data.hex()}")
        self.send_queue.put(data)

    # --- внутренние потоки ---
    def _start_threads(self):
        if self._threads_started:
            return
        t1 = threading.Thread(target=self._serial_thread, daemon=True)
        t1.start()
        self._threads_started = True

    def _feed_protocol(self, data: bytes):
        if self.protocol:
            packets = self.protocol.feed(data)
            for pkt in packets:
                print(f"[PKT PARSED] {pkt}")
        else:
            print(f"[RX RAW] {data.hex()}")
