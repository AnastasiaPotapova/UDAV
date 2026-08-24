from PyQt5.QtWidgets import QPushButton
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QMessageBox, QApplication
import time
import logging
import os

from resource_path import resource_path


class ModesExecutor(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
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
        """OPEN/CLOSE <имя клапана>"""
        if len(parts) < 2:
            return
        name = parts[1].upper()
        value = 1 if parts[0].upper() == "OPEN" else 0

        valid_valves = ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8")

        if name in valid_valves:
            self.engine.set_element_state(name, value)
        else:
            logging.warning(f"Неизвестный клапан: {name}")

    # ------------------------------------------------------------------
    def _handle_device(self, parts):
        """ON/OFF <имя устройства> (насосы NI/NR)"""
        if len(parts) < 2:
            return
        name = parts[1].upper()
        value = 1 if parts[0].upper() == "ON" else 0

        valid_devices = ("NI", "NR")

        if name in valid_devices:
            self.engine.set_element_state(name, value)
        else:
            logging.warning(f"Неизвестное или неуправляемое устройство: {name}")

    # ------------------------------------------------------------------
    def _handle_check(self, parts):
        if len(parts) < 2:
            return
        sensor = parts[1].upper()
        name_map = {"P1": "MIDA", "P2": "Magdischarge", "P3": "ThermalIndicator"}

        if sensor in name_map:
            val = self.engine.last_data.get(name_map[sensor])
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
            end_time = time.time() + delay
            while time.time() < end_time:
                if not self.running:
                    return
                QApplication.processEvents()
                time.sleep(0.05)
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
                val = self.engine.last_data.get(field)
                if val is None:
                    QApplication.processEvents()
                    time.sleep(0.2)
                    continue

                if ((op == "<" and val < threshold) or
                    (op == ">" and val > threshold)):
                    logging.info(f"{sensor} достиг {val:.3f}")
                    break

                QApplication.processEvents()
                time.sleep(0.2)

    # ------------------------------------------------------------------
    def _handle_set(self, parts):
        """
        SET PRESSURE P2 USING VF FORMULA
        """
        if len(parts) >= 5 and parts[1].upper() == "PRESSURE":
            target = parts[2].upper()
            if parts[3].upper() == "USING" and parts[4].upper() == "VF":
                logging.info(f"Установка давления {target} с помощью клапана VF (по формуле)")
                # TODO: здесь должен быть реальный алгоритм регулирования VF
                self.engine.set_element_state("VF", 1)
                time.sleep(1)
                self.engine.set_element_state("VF", 0)
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
            val = self.engine.last_data.get(field) if field else None
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

            for k, v in self.variables.items():
                formula = formula.replace(k, str(v))

            result = eval(formula)
            self.variables[var] = result
            logging.info(f"{var} = {result:.5f}")
        except Exception as e:
            logging.warning(f"Ошибка вычисления CALC: {e}")


class ModesManager:
    def __init__(self, layout, engine, filepath="modes.txt"):
        self.layout = layout
        self.filepath = resource_path(filepath)
        self.engine = engine
        self.programs = {}
        self.executor = ModesExecutor(engine)
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