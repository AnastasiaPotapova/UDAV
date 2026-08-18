from PyQt5.QtWidgets import QPushButton
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QMessageBox, QApplication
import time
import logging
import os

class ModesExecutor(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, serial_worker):
        super().__init__()
        self.serial_worker = serial_worker
        self.running = False
        self.variables = {}  # для сохранения значений: {"P2_BEFORE": 123.4, "K": 0.5}

    # ------------------------------------------------------------------
    def execute(self, name, commands):
        self.running = True
        try:
            for raw_cmd in commands:
                if not self.running:
                    self.finished.emit(f"Сценарий {name} прерван.")
                    return
                line = raw_cmd.strip()
                if not line or line.startswith("#"):
                    continue
                self.process_command(line)
                QApplication.processEvents()
            self.finished.emit(f"Сценарий {name} завершён.")
        except Exception as e:
            self.error.emit(str(e))

    # ------------------------------------------------------------------
    def stop(self):
        self.running = False

    # ------------------------------------------------------------------
    def process_command(self, line: str):
        logging.info(f"[MODES] {line}")
        parts = line.split()
        if not parts:
            return
        cmd = parts[0].upper()

        if cmd in ("OPEN", "CLOSE"):
            self._handle_valve(parts)

        elif cmd in ("ON", "OFF"):
            self._handle_device(parts)

        elif cmd == "WAIT":
            self._handle_wait(parts)

        elif cmd == "CHECK":
            self._handle_check(parts)

        elif cmd == "MESSAGE":
            text = line.split("MESSAGE", 1)[1].strip().strip('"')
            QMessageBox.information(None, "Сообщение", text)

        elif cmd == "CONFIRM":
            text = line.split("CONFIRM", 1)[1].strip().strip('"')
            res = QMessageBox.question(None, "Подтверждение", text,
                                       QMessageBox.Yes | QMessageBox.No)
            if res == QMessageBox.No:
                self.stop()

        elif cmd == "STOP":
            self.stop()
            logging.info("Сценарий остановлен пользователем.")

        elif cmd == "SET":
            self._handle_set(parts)

        elif cmd == "SAVE":
            self._handle_save(parts)

        elif cmd == "CALC":
            self._handle_calc(line)

        else:
            logging.warning(f"Неизвестная команда: {line}")

    # ------------------------------------------------------------------
    def _handle_valve(self, parts):
        if len(parts) < 2:
            return
        name = parts[1].upper()
        value = 1 if parts[0].upper() == "OPEN" else 0

        valve_map = {
            "V1": 0x06, "V3": 0x06, "V6": 0x06, "V7": 0x06,
            "V2": 0x07,
            "V4": 0x08, "V5": 0x08, "V8": 0x08,
            "VF": 0x09,
        }

        if name in valve_map:
            self.serial_worker.send_command(valve_map[name], bytes([value]))
        else:
            logging.warning(f"Неизвестный клапан: {name}")

    # ------------------------------------------------------------------
    def _handle_device(self, parts):
        if len(parts) < 2:
            return
        name = parts[1].upper()
        value = 1 if parts[0].upper() == "ON" else 0

        device_map = {
            "NI": 0x02,
            "NR": 0x03,
            "P3": 0x09,
        }

        if name in device_map:
            self.serial_worker.send_command(device_map[name], bytes([value]))
        else:
            logging.warning(f"Неизвестное устройство: {name}")

    # ------------------------------------------------------------------
    def _handle_check(self, parts):
        if len(parts) < 2:
            return
        sensor = parts[1].upper()
        name_map = {"P1": "MIDA", "P2": "Magdischarge", "P3": "ThermalIndicator"}

        if sensor in name_map and hasattr(self.serial_worker, "last_data"):
            val = self.serial_worker.last_data.get(name_map[sensor], None)
            if val is not None:
                QMessageBox.information(None, "Контроль датчика",
                                        f"{sensor}: {val:.3f} Па")
                return
        QMessageBox.information(None, "Контроль датчика",
                                f"Проверьте показания {sensor} (данные недоступны)")

    # ------------------------------------------------------------------
    def _handle_wait(self, parts):
        if len(parts) == 2 and parts[1].replace('.', '', 1).isdigit():
            delay = float(parts[1])
            logging.info(f"Ждём {delay} секунд...")
            time.sleep(delay)
            return

        if len(parts) >= 5 and parts[1].upper() == "UNTIL":
            sensor = parts[2].upper()
            op = parts[3]
            try:
                threshold = float(parts[4])
            except ValueError:
                logging.warning(f"Некорректное значение в WAIT: {parts}")
                return

            name_map = {"P1": "MIDA", "P2": "Magdischarge", "P3": "ThermalIndicator"}
            field = name_map.get(sensor)
            if not field:
                logging.warning(f"Неизвестный датчик: {sensor}")
                return

            logging.info(f"Ждём пока {sensor} {op} {threshold}")
            while self.running:
                data = getattr(self.serial_worker, "last_data", {})
                val = data.get(field)
                if val is None:
                    time.sleep(0.5)
                    continue

                if ((op == "<" and val < threshold) or
                    (op == ">" and val > threshold)):
                    logging.info(f"{sensor} достиг {val:.3f}")
                    break
                time.sleep(0.5)

    # ------------------------------------------------------------------
    def _handle_set(self, parts):
        """
        SET PRESSURE P2 USING VF FORMULA
        """
        if len(parts) >= 5 and parts[1].upper() == "PRESSURE":
            target = parts[2].upper()
            if parts[3].upper() == "USING" and parts[4].upper() == "VF":
                logging.info(f"Установка давления {target} с помощью клапана VF (по формуле)")
                # здесь можно вставить управляющий алгоритм по формуле
                # пока просто пример:
                self.serial_worker.send_command(0x09, bytes([1]))
                time.sleep(1)
                self.serial_worker.send_command(0x09, bytes([0]))
            else:
                logging.warning(f"Неизвестная конструкция SET: {parts}")
        else:
            logging.warning(f"Некорректная команда SET: {parts}")

    # ------------------------------------------------------------------
    def _handle_save(self, parts):
        """
        SAVE P2 AS P2_BEFORE
        """
        if len(parts) >= 4 and parts[2].upper() == "AS":
            sensor = parts[1].upper()
            varname = parts[3].upper()
            name_map = {"P1": "MIDA", "P2": "Magdischarge", "P3": "ThermalIndicator"}
            field = name_map.get(sensor)
            val = getattr(self.serial_worker, "last_data", {}).get(field)
            if val is not None:
                self.variables[varname] = val
                logging.info(f"Сохранено {sensor}={val:.3f} как {varname}")
            else:
                logging.warning(f"Не удалось сохранить {sensor}: данных нет")
        else:
            logging.warning(f"Некорректная команда SAVE: {parts}")

    # ------------------------------------------------------------------
    def _handle_calc(self, line: str):
        """
        CALC K = P2_AFTER / P2_BEFORE
        """
        try:
            _, expr = line.split("CALC", 1)
            expr = expr.strip()
            left, right = expr.split("=", 1)
            var = left.strip()
            formula = right.strip()

            # заменяем имена переменных на их значения
            for k, v in self.variables.items():
                formula = formula.replace(k, str(v))

            result = eval(formula)
            self.variables[var] = result
            logging.info(f"{var} = {result:.5f}")
        except Exception as e:
            logging.warning(f"Ошибка вычисления CALC: {e}")



class ModesManager:
    def __init__(self, layout, serial_worker, filepath="modes.txt"):
        self.layout = layout
        self.filepath = filepath
        self.serial_worker = serial_worker
        self.programs = {}
        self.executor = ModesExecutor(serial_worker)
        self.load_programs()
        self.generate_buttons()

    def load_programs(self):
        current_name = None
        current_lines = []
        if not os.path.exists(self.filepath):
            QMessageBox.critical(None, "Ошибка", f"Файл {self.filepath} не найден")
            return
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    if current_name:
                        self.programs[current_name] = current_lines
                    current_name = line[1:-1].strip()
                    current_lines = []
                else:
                    current_lines.append(line)
        if current_name:
            self.programs[current_name] = current_lines

    def generate_buttons(self):
        for i in reversed(range(self.layout.count())):
            w = self.layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        for name in self.programs.keys():
            btn = QPushButton(name)
            btn.clicked.connect(lambda _, n=name: self.run_program(n))
            self.layout.addWidget(btn)

    def run_program(self, name):
        commands = self.programs.get(name, [])
        if not commands:
            QMessageBox.warning(None, "Ошибка", f"Пустой сценарий: {name}")
            return
        self.executor.execute(name, commands)
