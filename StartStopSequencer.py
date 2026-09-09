"""
Логика кнопок "Запуск" и "Остановка" (ТЗ_к_ПО_2.docx, п.1 - процедуру
описал Александр).

Обе процедуры выполняются как последовательность шагов в строгом порядке:
включение/выключение насосов и клапанов, подтверждения оператора и ожидание
показаний датчиков давления (P2 - МИДА-15/магниторазрядный, P3 -
сенсор-магнетрон). Каждое действие на оборудование идёт через уже
существующие Engine.set_device()/set_valve() - те же методы, что использует
остальной интерфейс (схема, окно "Установка давления"), поэтому локальное
состояние (Engine.system_status) и схема на экране остаются согласованными.

Переход к следующему клапану/насосу в процедуре ждёт РЕАЛЬНОГО подтверждения
срабатывания от контроллера (по полям du16/du63/electro_valves/
forvacuum_state/tmn_state в опросе exchange_packet, см. _device_confirmed
ниже), а не фиксированную задержку по таймеру: например, V3 включается
только после того, как в очередном опросе контроллер подтвердит, что V1
уже открыт. Это устраняет и саму причину гонки при групповых
командах (см. Engine.commanded_status), и даёт более честную защиту от
реального отказа оборудования - если клапан физически не сработал,
процедура так и останется на этом шаге (с доступной кнопкой "Отмена"),
а не продолжит слепо через 2 секунды.

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

# Датчики хранятся в Engine.last_data под этими именами полей.
# ВНИМАНИЕ: P1/P3 здесь намеренно НЕ совпадают с MainWindow._update_values_bar -
# по прямому указанию пользователя (проверено на реальной установке) для
# графиков и для порогового условия готовности по P3 (сенсор-магнетрон, шаг
# "Ожидание показаний магнетрона") нужен именно этот, "перевёрнутый" порядок.
# Иначе шаг ждёт P3 ≤ 1e-2 Па по полю, которое реально не соответствует
# датчику P3, и процедура "Запуск" зависает на этом шаге навсегда (окно
# процедуры модальное - см. SequenceDialog, поэтому это выглядит как "не
# работают никакие нажатия клапанов и других процедур").
SENSOR_FIELDS = {
    "P1": "thermal_pressure",
    "P2": "magdischarge_pressure",
    "P3": "mida_pressure",
}


def _read_sensor(engine, sensor: str):
    field = SENSOR_FIELDS.get(sensor)
    if not field:
        return None
    return engine.last_data.get(field)


# ---------------------------------------------------------------------------
# Подтверждение срабатывания клапана/насоса по данным опроса контроллера
# ---------------------------------------------------------------------------
def _device_confirmed(engine, target: str, on: bool):
    """True/False - контроллер в последнем опросе (Engine.last_data)
    подтвердил (или ещё нет) фактическое состояние target.
    None - для этого target нет способа подтвердить состояние по телеметрии
    (нет ни одного опроса ещё, или протокол не даёт такого поля) - в этом
    случае вызывающий код не блокирует процедуру, а идёт дальше сразу же."""
    data = engine.last_data
    if not data:
        return False  # опроса ещё не было ни разу - ждём первый пакет

    if target == "NI":
        value = data.get("forvacuum_state")
        if value is None:
            return None
        return bool(value) == on

    if target == "NR":
        # tmn_state: 0-OFF, 1-ACCELERATION, 2-NOMINAL - "включен" это
        # любое не-OFF состояние
        value = data.get("tmn_state")
        if value is None:
            return None
        return (value != 0) == on

    if target in ("V1", "V3", "V6", "V7"):
        du16 = data.get("du16")
        if not du16 or target not in du16:
            return None
        return bool(du16[target]) == on

    if target == "V2":
        value = data.get("du63")
        if value is None:
            return None
        return bool(value) == on

    if target in ("V4", "V5", "V8"):
        electro = data.get("electro_valves")
        if not electro or target not in electro:
            return None
        return bool(electro[target]) == on

    return None


# ---------------------------------------------------------------------------
# Описание шагов процедур "Запуск" / "Остановка"
# ---------------------------------------------------------------------------
# kind == "cmd"     -> включить/выключить насос (device=True) или клапан
#                      (device=False); если "confirm": True - следующий шаг
#                      начнётся только когда контроллер подтвердит реальное
#                      срабатывание (см. _device_confirmed), а не сразу
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

        {"kind": "cmd", "target": "V1", "device": False, "on": True, "confirm": True,
         "label": "Открытие клапана V1"},
        {"kind": "cmd", "target": "V3", "device": False, "on": True, "confirm": True,
         "label": "Открытие клапана V3"},
        {"kind": "cmd", "target": "V2", "device": False, "on": True, "confirm": True,
         "label": "Открытие клапана V2"},
        {"kind": "cmd", "target": "V4", "device": False, "on": True, "confirm": True,
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
        # Проверка V5 перед остальными шагами (по прямому запросу
        # пользователя): если V5 уже включён, Engine._send_element_command
        # не отправит повторную команду (см. "уже в этом состоянии") и шаг
        # с confirm=True пройдёт мгновенно по уже имеющейся телеметрии;
        # если V5 выключен - команда на включение отправляется и шаг ждёт
        # реального подтверждения от контроллера, как и остальные клапаны.
        {"kind": "cmd", "target": "V5", "device": False, "on": True, "confirm": True,
         "label": "Проверка клапана V5 (включение, если выключен)"},

        {"kind": "cmd", "target": "V8", "device": False, "on": False, "confirm": True,
         "label": "Закрытие клапана V8"},
        {"kind": "cmd", "target": "V4", "device": False, "on": False, "confirm": True,
         "label": "Закрытие клапана V4"},
        {"kind": "cmd", "target": "V2", "device": False, "on": False, "confirm": True,
         "label": "Закрытие клапана V2"},
        {"kind": "cmd", "target": "NR", "device": True, "on": False,
         "label": "Выключение турбомолекулярного насоса (NR)"},
        {"kind": "confirm",
         "label": "Подтверждение оператора: насос выключился",
         "text": "Подтвердите, что насос (NR) выключился"},

        {"kind": "cmd", "target": "V3", "device": False, "on": False, "confirm": True,
         "label": "Закрытие клапана V3"},
        {"kind": "cmd", "target": "V1", "device": False, "on": False, "confirm": True,
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
            if step.get("confirm"):
                self._start_confirm_wait(step)
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

    def _start_confirm_wait(self, step):
        """Ждём реального подтверждения от контроллера (см.
        _device_confirmed), а не таймер - только после этого переходим к
        следующему клапану/насосу в процедуре."""
        confirmed = _device_confirmed(self.engine, step["target"], step["on"])
        if confirmed or confirmed is None:
            if confirmed is None:
                logging.warning(
                    'Процедура "%s": для %s нет поля подтверждения в опросе '
                    "контроллера - шаг пропущен без ожидания срабатывания",
                    self.dialog.windowTitle(), step["target"],
                )
            self._advance()
            return
        self.dialog.set_status(
            (step.get("text") or step["label"]) + " — ожидание подтверждения от контроллера…"
        )
        self._poll_timer.start()

    def _check_wait_condition(self):
        if self._stopped:
            self._poll_timer.stop()
            return
        step = self.steps[self.index]
        if step["kind"] == "wait":
            if self._condition_met(step):
                self._poll_timer.stop()
                self._advance()
        elif step["kind"] == "cmd" and step.get("confirm"):
            confirmed = _device_confirmed(self.engine, step["target"], step["on"])
            if confirmed or confirmed is None:
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