"""
Процедура "Статическое расширение" (кнопка в левой панели MainWindow).

1. Оператор вводит задаваемое давление Pвв (как в "Установке давления").
2. n = 1, если Pвв >= 10 Па, иначе n = 2.
3. Выбор ОДНОГО варианта коэффициентов а)/б)/в)/г) (строки таблицы
   "Коэффициенты статического расширения", по умолчанию выбран а).
4. Показываются редактируемые поля k и q. Если оператор меняет значение -
   активируется кнопка "Применить": изменённые k/q используются ТОЛЬКО в
   этом запуске процедуры, в таблицу и файл они НЕ записываются.

Вариант определяет два шага процедуры:
    шаг 8  (V8):          а, в - открыть V8;  б, г - закрыть V8
    шаг 14 (и 23 при n=2): а, б - открыть V4; в, г - закрыть V4

Шаги (n = 1):
     6. Pисх = Pвв / k                 (n = 2: Pисх = Pвв / k^2)
     7. Закрыть V4                     (отсюда отсчитывается T)
     8. V8 - см. выше
     9. Установка Pисх в малом объёме (контроль по P2)
    10. Ожидание 1 мин
    11. Ожидание P3 < 1E-2 Па, p0 = P3
    12. p1 = текущее P2
    13. Закрыть V2
    14. V4 - см. выше
    15. Pстат = k*Pисх*(1 + (p0/p1)*((1/k) - 1)) + q*T
    16. Повтор расчёта каждые 3 с до "Стоп" (n = 1)
        или до "Перейти к следующему шагу" (n = 2)
Дальше только для n = 2:
    17. Закрыть V4                     (T отсчитывается заново)
    18. Открыть V2
    19-20. Ожидание P3 < 1E-2 Па, p0 = P3
    21. Закрыть V2
    22. Pисх = последнее Pстат
    23. V4 - см. выше
    24. Расчёт Pстат (как в п.15)
    25. Повтор расчёта каждые 3 с до "Стоп"

"Стоп" в любой момент закрывает окно и прекращает процедуру - дальнейшие
команды на оборудование не отправляются, клапаны остаются в том состоянии,
в которое их успели перевести (как "Отмена" в "Запуске"/"Остановке").

Последнее рассчитанное Pстат выводится и в нижней панели ("Р стат.") через
Engine.set_static_pressure().
"""
import logging
import time

from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QPushButton, QLabel,
    QRadioButton, QButtonGroup, QStackedWidget, QListWidget, QListWidgetItem,
    QPlainTextEdit, QGroupBox, QFrame,
)

from ExpansionCoefficients import VARIANT_LETTERS, format_number, parse_number
from PressureWindow import MIN_PRESSURE_PA, MAX_PRESSURE_PA, parse_pressure
from StartStopSequencer import _device_confirmed, _read_sensor

# Граница выбора числа расширений: Pвв >= 10 Па -> n=1, строго меньше -> n=2
N_THRESHOLD_PA = 10.0
# Требование к остаточному давлению в большом объёме (P3) перед расширением
P0_THRESHOLD_PA = 1e-2
# Пауза после установки исходного давления
SETTLE_DELAY_S = 60
# Период повторного расчёта Pстат
RECALC_INTERVAL_MS = 3000
# Считаем, что исходное давление установилось, когда P2 отличается от
# Pисх не больше чем на эту долю (оператор может перейти дальше вручную)
PRESSURE_TOLERANCE = 0.05
POLL_INTERVAL_MS = 300


def variant_flags(variant: int):
    """(открыть ли V8 на шаге 8, открыть ли V4 на шаге 14/23) для варианта
    0..3 (а..г)."""
    v8_open = variant in (0, 2)   # а, в - открыть V8; б, г - закрыть
    v4_open = variant in (0, 1)   # а, б - открыть V4; в, г - закрыть
    return v8_open, v4_open


def calc_static_pressure(k, p_init, p0, p1, q, t):
    """Pстат = k*Pисх*(1 + (p0/p1)*((1/k) - 1)) + q*T"""
    return k * p_init * (1 + (p0 / p1) * ((1 / k) - 1)) + q * t


# ---------------------------------------------------------------------------
# Окно ввода давления и выбора коэффициентов (п. 1-4)
# ---------------------------------------------------------------------------
class StaticExpansionSetupWindow(QWidget):
    """start_requested(dict): p_target, n, variant (0..3), k, q, edited."""

    start_requested = pyqtSignal(dict)

    def __init__(self, coefficients: list):
        super().__init__()
        self.setWindowTitle("Статическое расширение")
        self.setMinimumWidth(420)
        self.setWindowModality(Qt.ApplicationModal)
        self.coefficients = coefficients
        self.p_target = None
        self.n = None

        layout = QVBoxLayout(self)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)
        self.pages.addWidget(self._build_pressure_page())
        self.pages.addWidget(self._build_coefficients_page())

    # ------------------------------------------------------------ страница 1
    def _build_pressure_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        form = QFormLayout()
        row = QHBoxLayout()
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("например, 10 или 1Е-1")
        self.value_edit.returnPressed.connect(self._on_pressure_ok)
        row.addWidget(self.value_edit)
        row.addWidget(QLabel("Па"))
        form.addRow("Задать Р:", row)
        layout.addLayout(form)

        hint = QLabel(f"Диапазон: от {MIN_PRESSURE_PA:g} до {MAX_PRESSURE_PA:g} Па")
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        self.pressure_error = QLabel("")
        self.pressure_error.setStyleSheet("color: #e74c3c;")
        layout.addWidget(self.pressure_error)
        layout.addStretch()

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Ок")
        ok_btn.clicked.connect(self._on_pressure_ok)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
        return page

    def _on_pressure_ok(self):
        value = parse_pressure(self.value_edit.text())
        if value is None:
            self.pressure_error.setText("Некорректное значение давления")
            return
        if not (MIN_PRESSURE_PA <= value <= MAX_PRESSURE_PA):
            self.pressure_error.setText(
                f"Значение должно быть в диапазоне от {MIN_PRESSURE_PA:g} до {MAX_PRESSURE_PA:g} Па"
            )
            return
        self.pressure_error.setText("")
        self.p_target = value
        self.n = 1 if value >= N_THRESHOLD_PA else 2
        cond = f"≥ {N_THRESHOLD_PA:g}" if self.n == 1 else f"< {N_THRESHOLD_PA:g}"
        self.summary_label.setText(
            f"Задано P = {format_number(value)} Па ({cond} Па) → n = {self.n}"
        )
        self.pages.setCurrentIndex(1)

    # ------------------------------------------------------------ страница 2
    def _build_coefficients_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.summary_label)

        box = QGroupBox("Вариант коэффициентов")
        box_layout = QVBoxLayout(box)
        self.variant_group = QButtonGroup(self)
        for i, coeff in enumerate(self.coefficients):
            rb = QRadioButton(
                f"{VARIANT_LETTERS[i]}) k = {format_number(coeff['k'])}, "
                f"q0 = {format_number(coeff['q0'])}"
            )
            self.variant_group.addButton(rb, i)
            box_layout.addWidget(rb)
        self.variant_group.button(0).setChecked(True)  # по умолчанию - первый
        self.variant_group.buttonClicked.connect(lambda _: self._fill_fields())
        layout.addWidget(box)

        question = QLabel("Оставить табличные коэффициенты k и q или изменить?")
        question.setWordWrap(True)
        layout.addWidget(question)

        form = QFormLayout()
        self.k_edit = QLineEdit()
        self.q_edit = QLineEdit()
        self.k_edit.textChanged.connect(self._on_fields_changed)
        self.q_edit.textChanged.connect(self._on_fields_changed)
        form.addRow("k:", self.k_edit)
        form.addRow("q:", self.q_edit)
        layout.addLayout(form)

        note = QLabel("Изменённые значения используются только в этом запуске "
                      "и не сохраняются в таблицу.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)

        self.coeff_error = QLabel("")
        self.coeff_error.setStyleSheet("color: #e74c3c;")
        layout.addWidget(self.coeff_error)

        btn_row = QHBoxLayout()
        back_btn = QPushButton("Назад")
        back_btn.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        self.keep_btn = QPushButton("Оставить табличные")
        self.keep_btn.clicked.connect(self._on_keep)
        self.apply_btn = QPushButton("Применить")
        self.apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(back_btn)
        btn_row.addWidget(self.keep_btn)
        btn_row.addWidget(self.apply_btn)
        layout.addLayout(btn_row)

        self._fill_fields()
        return page

    def _selected(self):
        return self.variant_group.checkedId()

    def _fill_fields(self):
        coeff = self.coefficients[self._selected()]
        self.k_edit.setText(format_number(coeff["k"]))
        self.q_edit.setText(format_number(coeff["q0"]))
        self._on_fields_changed()

    def _on_fields_changed(self):
        coeff = self.coefficients[self._selected()]
        k = parse_number(self.k_edit.text())
        q = parse_number(self.q_edit.text())
        changed = (k != coeff["k"]) or (q != coeff["q0"])
        self.apply_btn.setEnabled(changed)
        self.coeff_error.setText("")

    def _on_keep(self):
        coeff = self.coefficients[self._selected()]
        self._start(coeff["k"], coeff["q0"], edited=False)

    def _on_apply(self):
        k = parse_number(self.k_edit.text())
        q = parse_number(self.q_edit.text())
        if k is None or q is None:
            self.coeff_error.setText("Некорректное значение k или q")
            return
        if k == 0:
            self.coeff_error.setText("k не может быть равен 0")
            return
        self._start(k, q, edited=True)

    def _start(self, k, q, edited):
        p_init = self.p_target / (k if self.n == 1 else k ** 2)
        if not (MIN_PRESSURE_PA <= p_init <= MAX_PRESSURE_PA):
            self.coeff_error.setText(
                f"Исходное давление {format_number(p_init)} Па вне диапазона "
                f"{MIN_PRESSURE_PA:g}…{MAX_PRESSURE_PA:g} Па"
            )
            return
        self.start_requested.emit({
            "p_target": self.p_target,
            "n": self.n,
            "variant": self._selected(),
            "k": k,
            "q": q,
            "edited": edited,
        })
        self.close()


# ---------------------------------------------------------------------------
# Окно выполнения процедуры
# ---------------------------------------------------------------------------
class StaticExpansionDialog(QWidget):
    stop_clicked = pyqtSignal()
    next_clicked = pyqtSignal()

    def __init__(self, labels: list, title: str, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(title)
        self.setMinimumSize(560, 720)
        self._labels = labels
        self._allow_close = False

        layout = QVBoxLayout(self)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self.status_label)

        self.readings_label = QLabel("P2 = —    P3 = —")
        layout.addWidget(self.readings_label)

        self.list_widget = QListWidget()
        for label in labels:
            QListWidgetItem("   " + label, self.list_widget)
        self.list_widget.setFixedHeight(230)
        layout.addWidget(self.list_widget)

        formula_frame = QFrame()
        formula_frame.setFrameShape(QFrame.StyledPanel)
        formula_layout = QVBoxLayout(formula_frame)
        self.formula_label = QLabel("Pстат = k·Pисх·(1 + (p0/p1)·((1/k) − 1)) + q·T")
        self.formula_label.setWordWrap(True)
        self.formula_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.formula_label.setStyleSheet("font-size: 13px;")
        formula_layout.addWidget(self.formula_label)
        layout.addWidget(formula_frame)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.next_btn = QPushButton("Далее")
        self.next_btn.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold;")
        self.next_btn.clicked.connect(self.next_clicked.emit)
        self.next_btn.hide()
        btn_row.addWidget(self.next_btn)
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold;")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

    def set_status(self, text):
        self.status_label.setText(text)

    def set_progress(self, index):
        for row, label in enumerate(self._labels):
            prefix = "✓ " if row < index else ("▶ " if row == index else "   ")
            self.list_widget.item(row).setText(prefix + label)
        if 0 <= index < len(self._labels):
            self.list_widget.scrollToItem(self.list_widget.item(index))

    def add_log(self, text):
        stamp = time.strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{stamp}] {text}")

    def show_next(self, text=None):
        if text:
            self.next_btn.setText(text)
            self.next_btn.show()
        else:
            self.next_btn.hide()

    def force_close(self):
        self._allow_close = True
        self.close()

    def closeEvent(self, event):
        # крестик = "Стоп"
        if self._allow_close:
            event.accept()
        else:
            event.ignore()
            self.stop_clicked.emit()


class StaticExpansionRunner(QObject):
    finished = pyqtSignal()

    def __init__(self, engine, params: dict, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.p_target = params["p_target"]
        self.n = params["n"]
        self.variant = params["variant"]
        self.k = params["k"]
        self.q = params["q"]
        self.edited = params.get("edited", False)

        self.p_init = None     # Pисх
        self.p0 = None         # P3 перед расширением
        self.p1 = None         # P2 перед расширением
        self.p_stat = None     # последнее рассчитанное Pстат
        self.t_ref = None      # момент закрытия V4 (отсчёт T)

        self._stopped = False
        self._wait_check = None   # функция, возвращающая True, когда шаг завершён
        self.index = 0

        v8_open, v4_open = variant_flags(self.variant)
        v8_text = "Открытие клапана V8" if v8_open else "Закрытие клапана V8"
        v4_text = "Открытие клапана V4" if v4_open else "Закрытие клапана V4"
        final_loop_label = "Расчёт каждые 3 с (до «Стоп»)"

        self.steps = [
            ("Расчёт исходного давления", self._s_calc_initial),
            ("Закрытие клапана V4", lambda: self._s_valve("V4", False, start_t=True)),
            (v8_text, lambda: self._s_valve("V8", v8_open)),
            ("Установка исходного давления в малом объёме (P2)", self._s_set_pressure),
            ("Ожидание 1 минуты", lambda: self._s_delay(SETTLE_DELAY_S)),
            ("Проверка P3 < 1E-2 Па, запись p0", self._s_wait_p0),
            ("Запись текущего P2 (p1)", self._s_record_p1),
            ("Закрытие клапана V2", lambda: self._s_valve("V2", False)),
            (v4_text, lambda: self._s_valve("V4", v4_open)),
            ("Расчёт давления после расширения", self._s_calc_stat),
        ]
        if self.n == 1:
            self.steps.append((final_loop_label, lambda: self._s_loop(final=True)))
        else:
            self.steps += [
                ("Расчёт каждые 3 с (до «Перейти к следующему шагу»)",
                 lambda: self._s_loop(final=False)),
                ("Закрытие клапана V4", lambda: self._s_valve("V4", False, start_t=True)),
                ("Открытие клапана V2", lambda: self._s_valve("V2", True)),
                ("Ожидание P3 < 1E-2 Па, запись p0", self._s_wait_p0),
                ("Закрытие клапана V2", lambda: self._s_valve("V2", False)),
                ("Pисх = последнее Pстат", self._s_take_stat_as_initial),
                (v4_text, lambda: self._s_valve("V4", v4_open)),
                ("Расчёт давления после расширения", self._s_calc_stat),
                (final_loop_label, lambda: self._s_loop(final=True)),
            ]

        letter = VARIANT_LETTERS[self.variant]
        self.dialog = StaticExpansionDialog(
            [label for label, _ in self.steps],
            f"Статическое расширение: n = {self.n}, вариант {letter})",
        )
        self.dialog.stop_clicked.connect(self.stop)
        self.dialog.next_clicked.connect(self._on_next)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)

        self._recalc_timer = QTimer(self)
        self._recalc_timer.setInterval(RECALC_INTERVAL_MS)
        self._recalc_timer.timeout.connect(self._recalc)

        self._readings_timer = QTimer(self)
        self._readings_timer.setInterval(500)
        self._readings_timer.timeout.connect(self._update_readings)

    # ------------------------------------------------------------ запуск/стоп
    def start(self):
        d = self.dialog
        d.add_log(
            f"Задано P = {format_number(self.p_target)} Па, n = {self.n}, "
            f"вариант {VARIANT_LETTERS[self.variant]}), k = {format_number(self.k)}, "
            f"q = {format_number(self.q)}"
            + (" (изменены вручную, только для этого запуска)" if self.edited else " (табличные)")
        )
        logging.info("Статическое расширение: старт, P=%s n=%s вариант=%s k=%s q=%s",
                     self.p_target, self.n, self.variant, self.k, self.q)
        d.show()
        self._readings_timer.start()
        self._update_readings()
        self._run_step()

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self._poll_timer.stop()
        self._recalc_timer.stop()
        self._readings_timer.stop()
        logging.info("Статическое расширение: остановлено на шаге %s/%s",
                     self.index + 1, len(self.steps))
        self.dialog.force_close()
        self.finished.emit()

    # ------------------------------------------------------------ цикл шагов
    def _run_step(self):
        if self._stopped:
            return
        if self.index >= len(self.steps):
            return
        label, action = self.steps[self.index]
        self.dialog.set_progress(self.index)
        self.dialog.set_status(label)
        self.dialog.show_next(None)
        action()

    def _advance(self):
        if self._stopped:
            return
        self._poll_timer.stop()
        self._wait_check = None
        self.index += 1
        self._run_step()

    def _wait_until(self, check):
        """Шаг завершается, когда check() вернёт True (опрос раз в 300 мс)."""
        if check():
            self._advance()
            return
        self._wait_check = check
        self._poll_timer.start()

    def _poll(self):
        if self._stopped or self._wait_check is None:
            self._poll_timer.stop()
            return
        if self._wait_check():
            self._advance()

    def _on_next(self):
        """Кнопка "Далее"/"Перейти к следующему шагу"."""
        if self._stopped:
            return
        if self._recalc_timer.isActive():
            self._recalc_timer.stop()
        self.dialog.add_log("Оператор: переход к следующему шагу")
        self._advance()

    def _update_readings(self):
        p2 = _read_sensor(self.engine, "P2")
        p3 = _read_sensor(self.engine, "P3")
        self.dialog.readings_label.setText(
            f"Текущие: P2 = {format_number(p2) if p2 is not None else '—'} Па    "
            f"P3 = {format_number(p3) if p3 is not None else '—'} Па"
        )

    # ------------------------------------------------------------ шаги
    def _s_calc_initial(self):
        if self.n == 1:
            self.p_init = self.p_target / self.k
            text = (f"Pисх = Pвв / k = {format_number(self.p_target)} / "
                    f"{format_number(self.k)} = {format_number(self.p_init)} Па")
        else:
            self.p_init = self.p_target / self.k ** 2
            text = (f"Pисх = Pвв / k² = {format_number(self.p_target)} / "
                    f"{format_number(self.k)}² = {format_number(self.p_init)} Па")
        self.dialog.add_log(text)
        self._advance()

    def _s_valve(self, name, on, start_t=False):
        self.engine.set_valve(name, on)
        action = "открыть" if on else "закрыть"
        self.dialog.add_log(f"{name}: команда {action}")

        def check():
            confirmed = _device_confirmed(self.engine, name, on)
            if confirmed is None:
                logging.warning("Статическое расширение: нет подтверждения для %s в опросе", name)
                confirmed = True
            if confirmed:
                self.dialog.add_log(f"{name}: {'открыт' if on else 'закрыт'} (подтверждено контроллером)")
                if start_t:
                    self.t_ref = time.monotonic()
                    self.dialog.add_log("Начат отсчёт времени T")
            return confirmed

        self.dialog.set_status(f"{name}: {action} — ожидание подтверждения от контроллера…")
        self._wait_until(check)

    def _s_set_pressure(self):
        # "в малом объёме" - принудительно режим малого объёма в EEPROM,
        # независимо от порога 1000 Па в Engine.set_pressure
        self.engine.set_pressure(self.p_init, volume_mode=self.engine.EXPANSION_VOLUME_SMALL)
        target = self.p_init
        self.dialog.add_log(f"Уставка давления {format_number(target)} Па (малый объём)")
        self.dialog.set_status(
            f"Установка Pисх = {format_number(target)} Па, контроль по P2 "
            f"(±{PRESSURE_TOLERANCE * 100:g} %). «Далее» - перейти вручную."
        )
        self.dialog.show_next("Далее")

        def check():
            p2 = _read_sensor(self.engine, "P2")
            if p2 is None:
                return False
            if abs(p2 - target) <= PRESSURE_TOLERANCE * abs(target):
                self.dialog.add_log(f"Давление установлено: P2 = {format_number(p2)} Па")
                return True
            return False

        self._wait_until(check)

    def _s_delay(self, seconds):
        end = time.monotonic() + seconds

        def check():
            left = end - time.monotonic()
            if left <= 0:
                self.dialog.add_log(f"Выдержка {seconds} с завершена")
                return True
            self.dialog.set_status(f"Ожидание: осталось {int(left) + 1} с")
            return False

        self._wait_until(check)

    def _s_wait_p0(self):
        self.dialog.set_status(f"Ожидание P3 < {P0_THRESHOLD_PA:g} Па…")

        def check():
            p3 = _read_sensor(self.engine, "P3")
            if p3 is not None and p3 < P0_THRESHOLD_PA:
                self.p0 = p3
                self.dialog.add_log(f"p0 = P3 = {format_number(p3)} Па")
                return True
            return False

        self._wait_until(check)

    def _s_record_p1(self):
        def check():
            p2 = _read_sensor(self.engine, "P2")
            if p2 is None:
                return False
            self.p1 = p2
            self.dialog.add_log(f"p1 = P2 = {format_number(p2)} Па")
            return True

        self._wait_until(check)

    def _s_take_stat_as_initial(self):
        self.p_init = self.p_stat
        self.dialog.add_log(f"Pисх = Pстат = {format_number(self.p_init)} Па")
        self._advance()

    def _s_calc_stat(self):
        self._calculate(log=True)
        self._advance()

    def _s_loop(self, final: bool):
        if not final:
            self.dialog.show_next("Перейти к следующему шагу")
            self.dialog.set_status("Расчёт Pстат каждые 3 с. «Перейти к следующему шагу» - продолжить.")
        else:
            self.dialog.set_status("Расчёт Pстат каждые 3 с. «Стоп» - завершить.")
        self._recalc_timer.start()

    def _recalc(self):
        if self._stopped:
            self._recalc_timer.stop()
            return
        self._calculate(log=False)

    # ------------------------------------------------------------ расчёт
    def _calculate(self, log: bool):
        k, q, p_init, p0, p1 = self.k, self.q, self.p_init, self.p0, self.p1
        t = time.monotonic() - self.t_ref if self.t_ref is not None else 0.0
        general = "Pстат = k·Pисх·(1 + (p0/p1)·((1/k) − 1)) + q·T"
        if p1 in (None, 0) or p0 is None or p_init is None:
            self.dialog.formula_label.setText(general + "\nНедостаточно данных для расчёта (p1 = 0?)")
            return
        result = calc_static_pressure(k, p_init, p0, p1, q, t)
        f = format_number
        substituted = (f"Pстат = {f(k)}·{f(p_init)}·(1 + ({f(p0)}/{f(p1)})·((1/{f(k)}) − 1))"
                       f" + {f(q)}·{t:.1f}".replace(".", ","))
        answer = f"Pстат = {f(result)} Па   (T = {t:.1f} с)".replace(".", ",", 1)
        self.dialog.formula_label.setText(f"{general}\n{substituted}\n{answer}")

        self.p_stat = result
        self.engine.set_static_pressure(result)
        if log:
            self.dialog.add_log(general)
            self.dialog.add_log(substituted)
            self.dialog.add_log(answer)
        else:
            self.dialog.add_log(f"T = {t:.1f} с → Pстат = {f(result)} Па".replace(".", ",", 1))
