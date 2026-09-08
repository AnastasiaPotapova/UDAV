"""
Логика кнопок "Запуск" и "Остановка" (ТЗ_к_ПО_2.docx, п.1 - процедуру
описал Александр).

Обе процедуры выполняются как последовательность шагов в строгом порядке:
включение/выключение насосов и клапанов с задержкой 2 секунды между
действиями, подтверждения оператора и ожидание показаний датчиков давления
(P2 - МИДА-15/магниторазрядный, P3 - сенсор-магнетрон). Каждое действие на
оборудование идёт через уже существующие Engine.set_device()/set_valve() -
те же методы, что использует остальной интерфейс (схема, окно "Установка
давления"), поэтому локальное состояние (Engine.system_status) и схема на
экране остаются согласованными.

Основные классы:
    SequenceDialog     - модальное окно с "дорожкой загрузки" (список шагов
                         + прогресс-бар), кнопками "Подтвердить"/"Отмена".
    SequenceRunner     - выполняет список шагов один за другим, реагируя на
                         клики в диалоге и на показания датчиков.
    StartStopController - подключается к кнопкам "Запуск"/"Остановка" в
                         MainWindow, управляет их цветом/доступностью и
                         запускает нужный SequenceRunner.
"""
import logging

from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton,
)

# ---------------------------------------------------------------------------
# Пороги давления по описанию процедуры
# ---------------------------------------------------------------------------
PRESSURE_V8_THRESHOLD_PA = 500.0        # ждём после открытия V8, перед NR
PRESSURE_TURBINE_THRESHOLD_PA = 150.0   # "турбина разогналась"
PRESSURE_MAGNETRON_THRESHOLD_PA = 1e-2  # готовность по показаниям магнетрона (P3)

# Датчики хранятся в Engine.last_data под этими именами полей
# (см. MainWindow._update_values_bar / pressure_format.py)
SENSOR_FIELDS = {
    "P1": "mida_pressure",
    "P2": "magdischarge_pressure",
    "P3": "thermal_pressure",
}


def _read_sensor(engine, sensor: str):
    field = SENSOR_FIELDS.get(sensor)
    if not field:
        return None
    return engine.last_data.get(field)


# ---------------------------------------------------------------------------
# Описание шагов процедур "Запуск" / "Остановка"
# ---------------------------------------------------------------------------
# kind == "cmd"     -> включить/выключить насос (device=True) или клапан
#                      (device=False), затем подождать delay_ms (мс)
# kind == "confirm" -> показать text и ждать клика "Подтвердить" (либо
#                      "Отмена" - тогда процедура прерывается и дальше
#                      никакие команды не отправляются)
# kind == "wait"    -> ждать выполнения условия sensor op threshold
# kind == "message" -> просто показать text и сразу перейти к следующему шагу

def build_start_steps():
    return [
        {"kind": "cmd", "target": "NI", "device": True, "on": True,
         "label": "Включение форвакуумного насоса (NI)"},
        {"kind": "confirm",
         "label": "Подтверждение оператора: насос включился",
         "text": "Подтвердите, что насос включился"},

        {"kind": "cmd", "target": "V1", "device": False, "on": True, "delay_ms": 2000,
         "label": "Открытие клапана V1"},
        {"kind": "cmd", "target": "V3", "device": False, "on": True, "delay_ms": 2000,
         "label": "Открытие клапана V3"},
        {"kind": "cmd", "target": "V2", "device": False, "on": True, "delay_ms": 2000,
         "label": "Открытие клапана V2"},
        {"kind": "cmd", "target": "V4", "device": False, "on": True, "delay_ms": 2000,
         "label": "Открытие клапана V4"},
        {"kind": "cmd", "target": "V8", "device": False, "on": True,
         "label": "Открытие клапана V8"},
        {"kind": "wait", "sensor": "P2", "op": "<", "threshold": PRESSURE_V8_THRESHOLD_PA,
         "label": f"Ожидание давления (P2 < {PRESSURE_V8_THRESHOLD_PA:g} Па)"},

        {"kind": "confirm",
         "label": "Подтверждение оператора: давление достигнуто",
         "text": "Нужное давление достигнуто?"},

        {"kind": "cmd", "target": "NR", "device": True, "on": True,
         "label": "Включение турбомолекулярного насоса (NR)"},
        {"kind": "wait", "sensor": "P2", "op": "<", "threshold": PRESSURE_TURBINE_THRESHOLD_PA,
         "label": f"Ожидание разгона турбины (P2 < {PRESSURE_TURBINE_THRESHOLD_PA:g} Па)"},

        {"kind": "confirm",
         "label": "Подтверждение оператора: турбина разогналась",
         "text": "Турбина разогналась. Подтвердите."},

        {"kind": "message",
         "label": "Сообщение оператору: включить магнетрон",
         "text": "Включите магнетрон"},
        {"kind": "wait", "sensor": "P3", "op": "<=", "threshold": PRESSURE_MAGNETRON_THRESHOLD_PA,
         "label": f"Ожидание показаний магнетрона (P3 ≤ {PRESSURE_MAGNETRON_THRESHOLD_PA:g} Па)"},

        {"kind": "message",
         "label": "Готовность",
         "text": "Установка готова к работе"},
    ]


def build_stop_steps():
    return [
        {"kind": "cmd", "target": "V8", "device": False, "on": False, "delay_ms": 2000,
         "label": "Закрытие клапана V8"},
        {"kind": "cmd", "target": "V4", "device": False, "on": False, "delay_ms": 2000,
         "label": "Закрытие клапана V4"},
        {"kind": "cmd", "target": "V2", "device": False, "on": False, "delay_ms": 2000,
         "label": "Закрытие клапана V2"},
        {"kind": "cmd", "target": "NR", "device": True, "on": False,
         "label": "Выключение турбомолекулярного насоса (NR)"},
        {"kind": "confirm",
         "label": "Подтверждение оператора: насос выключился",
         "text": "Подтвердите, что насос (NR) выключился"},

        {"kind": "cmd", "target": "V3", "device": False, "on": False, "delay_ms": 2000,
         "label": "Закрытие клапана V3"},
        {"kind": "cmd", "target": "V1", "device": False, "on": False, "delay_ms": 2000,
         "label": "Закрытие клапана V1"},
        {"kind": "cmd", "target": "NI", "device": True, "on": False,
         "label": "Выключение форвакуумного насоса (NI)"},
        {"kind": "confirm",
         "label": "Подтверждение оператора: установка остановлена",
         "text": "Подтвердите, что установка остановлена"},
    ]


# ---------------------------------------------------------------------------
# Диалог с "дорожкой загрузки"
# ---------------------------------------------------------------------------
class SequenceDialog(QDialog):
    """Окно процедуры: список шагов, прогресс-бар, текст текущего действия и
    кнопки "Подтвердить"/"Отмена". Закрывается только программно (через
    force_close), крестик и Escape во время процедуры игнорируются, чтобы
    оператор не мог случайно потерять окно процедуры на середине действия -
    выход возможен только явной "Отмена"."""

    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, title: str, steps: list, parent=None):
        super().__init__(parent)
        self._allow_close = False
        self._labels = [step["label"] for step in steps]

        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)

        layout = QVBoxLayout(self)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, len(steps))
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.list_widget = QListWidget()
        for label in self._labels:
            QListWidgetItem("   " + label, self.list_widget)
        self.list_widget.setFixedHeight(220)
        layout.addWidget(self.list_widget, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.confirm_btn = QPushButton("Подтвердить")
        self.confirm_btn.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold;")
        self.confirm_btn.clicked.connect(self.confirmed.emit)
        self.confirm_btn.hide()
        btn_row.addWidget(self.confirm_btn)

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------ помощники
    def set_status(self, text: str):
        self.status_label.setText(text)

    def set_progress(self, index: int):
        """index - номер текущего (ещё не завершённого) шага."""
        self.progress.setValue(index)
        for row, label in enumerate(self._labels):
            if row < index:
                prefix = "✓ "  # ✓
            elif row == index:
                prefix = "▶ "  # ▶
            else:
                prefix = "   "
            self.list_widget.item(row).setText(prefix + label)

    def mark_all_done(self):
        self.progress.setValue(self.progress.maximum())
        for row, label in enumerate(self._labels):
            self.list_widget.item(row).setText("✓ " + label)

    def show_confirm_button(self, show: bool):
        self.confirm_btn.setVisible(show)

    def show_cancel_button(self, show: bool):
        self.cancel_btn.setVisible(show)

    def force_close(self):
        self._allow_close = True
        self.close()

    # ------------------------------------------------------------ защита от случайного закрытия
    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Выполнение шагов
# ---------------------------------------------------------------------------
class SequenceRunner(QObject):
    """Проигрывает список шагов, управляя Engine и диалогом SequenceDialog.

    finished(bool) - True, если процедура дошла до конца; False, если была
    прервана оператором ("Отмена"). После "Отмена" никакие дальнейшие
    команды на оборудование не отправляются - оборудование остаётся в том
    состоянии, в которое его успели перевести предыдущие шаги."""

    finished = pyqtSignal(bool)

    POLL_INTERVAL_MS = 300
    READY_MESSAGE_HOLD_MS = 1500

    def __init__(self, engine, dialog: SequenceDialog, steps: list, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.dialog = dialog
        self.steps = steps
        self.index = 0
        self._stopped = False

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._check_wait_condition)

        self.dialog.cancelled.connect(self._on_cancel)
        self.dialog.confirmed.connect(self._on_confirm)

    def start(self):
        self._run_step()

    # ------------------------------------------------------------ реакции оператора
    def _on_cancel(self):
        if self._stopped:
            return
        self._stopped = True
        self._poll_timer.stop()
        logging.info(
            'Процедура "%s" отменена оператором на шаге %s/%s',
            self.dialog.windowTitle(), self.index + 1, len(self.steps),
        )
        self.dialog.force_close()
        self.finished.emit(False)

    def _on_confirm(self):
        if self._stopped:
            return
        step = self.steps[self.index]
        if step["kind"] != "confirm":
            return
        self.dialog.show_confirm_button(False)
        self._advance()

    # ------------------------------------------------------------ основной цикл
    def _run_step(self):
        if self._stopped:
            return

        if self.index >= len(self.steps):
            self._on_all_done()
            return

        step = self.steps[self.index]
        self.dialog.set_progress(self.index)
        self.dialog.set_status(step.get("text") or step["label"])

        kind = step["kind"]
        if kind == "cmd":
            self.dialog.show_confirm_button(False)
            self._exec_cmd(step)
            delay = step.get("delay_ms", 0)
            if delay:
                QTimer.singleShot(delay, self._advance)
            else:
                self._advance()
        elif kind == "confirm":
            self.dialog.show_confirm_button(True)
            # дальше ждём клика "Подтвердить"/"Отмена" - см. _on_confirm/_on_cancel
        elif kind == "message":
            self.dialog.show_confirm_button(False)
            QTimer.singleShot(0, self._advance)
        elif kind == "wait":
            self.dialog.show_confirm_button(False)
            self._start_wait(step)
        else:
            logging.warning("Неизвестный тип шага в процедуре: %s", kind)
            self._advance()

    def _exec_cmd(self, step):
        target = step["target"]
        on = step["on"]
        if step.get("device"):
            self.engine.set_device(target, on)
        else:
            self.engine.set_valve(target, on)
        logging.info('Процедура "%s": %s -> %s', self.dialog.windowTitle(), target, "ON" if on else "OFF")

    def _start_wait(self, step):
        if self._condition_met(step):
            self._advance()
            return
        self._poll_timer.start()

    def _check_wait_condition(self):
        if self._stopped:
            self._poll_timer.stop()
            return
        step = self.steps[self.index]
        if self._condition_met(step):
            self._poll_timer.stop()
            self._advance()

    def _condition_met(self, step) -> bool:
        value = _read_sensor(self.engine, step["sensor"])
        if value is None:
            return False
        op = step["op"]
        threshold = step["threshold"]
        if op == "<":
            return value < threshold
        if op == "<=":
            return value <= threshold
        if op == ">":
            return value > threshold
        if op == ">=":
            return value >= threshold
        return False

    def _advance(self):
        if self._stopped:
            return
        self.index += 1
        self._run_step()

    def _on_all_done(self):
        self.dialog.mark_all_done()
        last_text = self.steps[-1].get("text") or self.steps[-1]["label"]
        self.dialog.set_status(last_text)
        self.dialog.show_confirm_button(False)
        self.dialog.show_cancel_button(False)
        logging.info('Процедура "%s" завершена успешно', self.dialog.windowTitle())
        QTimer.singleShot(self.READY_MESSAGE_HOLD_MS, self._close_and_finish)

    def _close_and_finish(self):
        self.dialog.force_close()
        self.finished.emit(True)


# ---------------------------------------------------------------------------
# Контроллер кнопок "Запуск"/"Остановка"
# ---------------------------------------------------------------------------
class StartStopController(QObject):
    """Управляет цветом/доступностью кнопок "Запуск" и "Остановка" и
    запускает соответствующую процедуру (SequenceRunner + SequenceDialog).

    Цвета кнопок:
        серый (idle)    - простой, кнопка доступна
        жёлтый (running)- процедура выполняется, обе кнопки недоступны
        зелёный "Запуск" (ready) - установка запущена, кнопка заблокирована
        зелёный "Остановка" (done) - процедура остановки только что
                                      завершена, кнопка на 2 секунды
                                      "мигает" зелёным перед возвратом к серому
    """

    _GRAY = "background-color: #9e9e9e; color: white;"
    _YELLOW = "background-color: #f1c40f; font-weight: bold;"
    _GREEN = "background-color: #2ecc71; color: white; font-weight: bold;"

    STOP_DONE_HOLD_MS = 2000

    def __init__(self, main_window, engine):
        super().__init__(main_window)
        self.main_window = main_window
        self.engine = engine
        self._runner = None
        self._dialog = None

        self._set_start_state("idle")
        self._set_stop_state("idle")

    # ------------------------------------------------------------ кнопка "Запуск"
    def _set_start_state(self, state: str):
        btn = self.main_window.start_btn
        if state == "idle":
            btn.setEnabled(True)
            btn.setStyleSheet(self._GRAY)
        elif state == "running":
            btn.setEnabled(False)
            btn.setStyleSheet(self._YELLOW)
        elif state == "ready":
            btn.setEnabled(False)
            btn.setStyleSheet(self._GREEN)

    # ------------------------------------------------------------ кнопка "Остановка"
    def _set_stop_state(self, state: str):
        btn = self.main_window.stop_btn
        if state == "idle":
            btn.setEnabled(True)
            btn.setStyleSheet(self._GRAY)
        elif state == "running":
            btn.setEnabled(False)
            btn.setStyleSheet(self._YELLOW)
        elif state == "done":
            btn.setEnabled(False)
            btn.setStyleSheet(self._GREEN)

    # ------------------------------------------------------------ "Запуск"
    def on_start_clicked(self):
        if self._runner is not None:
            return  # процедура уже выполняется

        self._set_start_state("running")
        self._set_stop_state("running")  # нельзя параллельно жать "Остановка"

        steps = build_start_steps()
        self._dialog = SequenceDialog("Запуск установки", steps, self.main_window)
        self._runner = SequenceRunner(self.engine, self._dialog, steps, self)
        self._runner.finished.connect(self._on_start_finished)
        self._dialog.show()
        self._runner.start()

    def _on_start_finished(self, ok: bool):
        self._runner = None
        self._dialog = None
        if ok:
            self._set_start_state("ready")
            self._set_stop_state("idle")  # установка запущена - "Остановка" доступна
        else:
            self._set_start_state("idle")
            self._set_stop_state("idle")

    # ------------------------------------------------------------ "Остановка"
    def on_stop_clicked(self):
        if self._runner is not None:
            return  # процедура уже выполняется

        self._set_start_state("running")  # нельзя параллельно жать "Запуск"
        self._set_stop_state("running")

        steps = build_stop_steps()
        self._dialog = SequenceDialog("Остановка установки", steps, self.main_window)
        self._runner = SequenceRunner(self.engine, self._dialog, steps, self)
        self._runner.finished.connect(self._on_stop_finished)
        self._dialog.show()
        self._runner.start()

    def _on_stop_finished(self, ok: bool):
        self._runner = None
        self._dialog = None
        if ok:
            self._set_start_state("idle")
            self._set_stop_state("done")
            QTimer.singleShot(self.STOP_DONE_HOLD_MS, self._reset_after_stop)
        else:
            self._set_start_state("idle")
            self._set_stop_state("idle")

    def _reset_after_stop(self):
        self._set_start_state("idle")
        self._set_stop_state("idle")
