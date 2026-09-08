import math
from collections import deque

from PyQt5.QtWidgets import QWidget, QVBoxLayout
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

from pressure_format import format_p1, format_p2, format_p3

# Верхние индексы для компактной подписи делений шкалы вида "1*10^3" -> "1·10³"
_SUPERSCRIPTS = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def _log_tick_label(value: float) -> str:
    """Подпись деления логарифмической шкалы в стиле ТЗ_к_ПО_2.docx, п.4:
    "0,1", "1", "10", "100", "1·10³", "1·10⁵" (запятая - десятичный
    разделитель, большие/малые числа - в виде 1·10^N)."""
    if value <= 0:
        return "0"
    exp = round(math.log10(value))
    if -2 <= exp <= 2:
        text = f"{value:g}"
        return text.replace(".", ",")
    return f"1·10{str(exp).translate(_SUPERSCRIPTS)}"


class GraphPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Настройки графиков
        self.MAX_POINTS = 100  # Максимальное количество точек на графике
        self.UPDATE_INTERVAL = 100  # Интервал обновления (мс)

        self.graph_name = ["МИДА-ДА-15 (Р1)", "МИДА-15 (Р2)", "СЕНСОР-МАГНЕТРОН (Р3)"]

        # Диапазоны измерений и деления шкалы - см. ТЗ_к_ПО_2.docx, п.4.
        # У Р1 и Р2 диапазон и отметки совпадают (от 1Е-1 до 1Е5), у Р3 -
        # свой набор отметок (от 1Е-3 до 100). Шкала логарифмическая, т.к.
        # диапазон измерений охватывает несколько порядков величины - это
        # и есть "динамичное" масштабирование, о котором просит ТЗ: график
        # сразу читаем и на 0,1 Па, и на 100 000 Па, без ручной перенастройки.
        self.axis_specs = [
            {"ylim": (1e-1, 1e5), "yticks": [1e-1, 1, 10, 100, 1e3, 1e5], "fmt": format_p1},
            {"ylim": (1e-1, 1e5), "yticks": [1e-1, 1, 10, 100, 1e3, 1e5], "fmt": format_p2},
            {"ylim": (1e-3, 100), "yticks": [1e-3, 1e-2, 1e-1, 1, 10, 100], "fmt": format_p3},
        ]

        # Инициализация данных для трёх графиков
        self.data = [deque(maxlen=self.MAX_POINTS) for _ in range(3)]
        self.timestamps = [deque(maxlen=self.MAX_POINTS) for _ in range(3)]

        # Создание макета
        self.layout = QVBoxLayout(self)

        # Создание трёх графиков
        self.figures = []
        self.canvases = []
        self.axes = []
        self.lines = []
        self.value_texts = []  # подпись текущего значения на каждом графике (ТЗ п.4)
        self.event_markers = []  # Хранит маркеры событий для каждого графика

        for i in range(3):
            spec = self.axis_specs[i]

            # Создаём фигуру и оси. constrained_layout сам пересчитывает
            # поля при каждой перерисовке - без него подписи левой шкалы
            # обрезаются, когда Qt сжимает канву уже, чем исходный figsize
            # (актуально теперь, когда шкала перенесена налево - ТЗ п.4)
            fig = Figure(figsize=(8, 3), layout="constrained")
            canvas = FigureCanvas(fig)
            ax = fig.add_subplot(111)

            # Шкала давления - слева (раньше была справа, см. ТЗ п.4)
            ax.yaxis.tick_left()
            ax.yaxis.set_label_position("left")

            # Логарифмическая шкала с фиксированными делениями под диапазон
            # конкретного датчика (ТЗ п.4)
            ax.set_yscale("log")
            ax.set_ylim(*spec["ylim"])
            ax.yaxis.set_major_locator(FixedLocator(spec["yticks"]))
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: _log_tick_label(v)))
            ax.yaxis.set_minor_locator(NullLocator())

            # Единицы измерения по вертикальной шкале - "Па", подписаны
            # сверху над шкалой (ТЗ п.4)
            ax.text(0.0, 1.06, "Па", transform=ax.transAxes,
                    fontsize=9, fontweight="bold", va="bottom", ha="left")

            # Горизонтальная шкала - время в секундах (ТЗ п.4)
            ax.xaxis.set_visible(True)
            ax.set_xlabel("t, с")

            ax.set_title(self.graph_name[i])

            # Инициализируем линию графика нижней границей шкалы, а не 0 -
            # на логарифмической шкале 0 не отображается
            line, = ax.plot([], [], color="blue")

            # Подпись текущего значения давления - совпадает со значением
            # в нижней строке измерений (ТЗ п.4)
            value_text = ax.text(
                0.98, 0.94, "", transform=ax.transAxes, ha="right", va="top",
                fontsize=11, fontweight="bold", color="blue",
                bbox=dict(boxstyle="round", fc="white", ec="blue", alpha=0.85),
            )

            # Устанавливаем начальные границы по X
            ax.set_xlim(0, self.MAX_POINTS)

            # Добавляем в списки
            self.figures.append(fig)
            self.canvases.append(canvas)
            self.axes.append(ax)
            self.lines.append(line)
            self.value_texts.append(value_text)
            self.event_markers.append([])

            # Добавляем график в макет
            self.layout.addWidget(canvas)

            # Заполняем начальные данные нижней границей шкалы датчика
            floor_value = spec["ylim"][0]
            for j in range(self.MAX_POINTS):
                self.timestamps[i].append(j)
                self.data[i].append(floor_value)

            # Обновляем линию
            line.set_data(self.timestamps[i], self.data[i])

    def update_plots(self, actual_data):
        """Обновляет данные на всех трёх графиках."""
        for i in range(3):
            value = actual_data[i]
            floor_value = self.axis_specs[i]["ylim"][0]

            # На логарифмической шкале нулевые/отрицательные значения не
            # отображаются - подставляем нижнюю границу диапазона датчика
            plot_value = value if value and value > 0 else floor_value

            self.data[i].append(plot_value)
            self.timestamps[i].append(self.timestamps[i][-1] + 1 if self.timestamps[i] else 0)

            # Обновляем линию
            self.lines[i].set_data(self.timestamps[i], self.data[i])

            # Подпись текущего значения - тот же формат, что и в нижней
            # строке измерений (ТЗ п.4/п.5)
            self.value_texts[i].set_text(self.axis_specs[i]["fmt"](value))

            # Сдвигаем видимую область, если данные выходят за правую границу
            if self.timestamps[i][-1] > self.axes[i].get_xlim()[1]:
                x_shift = self.timestamps[i][-1] - self.axes[i].get_xlim()[1]
                self.axes[i].set_xlim(
                    self.axes[i].get_xlim()[0] + x_shift,
                    self.axes[i].get_xlim()[1] + x_shift
                )

            # Обновляем маркеры событий (если есть)
            for marker_line, marker_point in self.event_markers[i]:
                marker_line.set_xdata([marker_line.get_xdata()[0]] * 2)
                marker_point.set_xdata([marker_line.get_xdata()[0]])
                marker_point.set_ydata([self.data[i][-1]])

            # Перерисовываем график
            self.canvases[i].draw()

    def mark_event(self):
        """Ставит маркер события на все три графика."""
        for i in range(3):
            if not self.timestamps[i]:
                continue  # Если данных нет, пропускаем

            # Получаем текущее время (последний timestamp)
            current_time = self.timestamps[i][-1]
            current_value = self.data[i][-1]

            # Создаём маркер (вертикальная линия + точка)
            ax = self.axes[i]
            marker_line = ax.axvline(x=current_time, color='red', alpha=0.5, linestyle='--')
            marker_point = ax.plot(current_time, current_value, 'ro')[0]

            # Добавляем маркеры в список
            self.event_markers[i].append((marker_line, marker_point))

            # Перерисовываем график
            self.canvases[i].draw()
