from collections import deque
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D


class GraphPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Настройки графиков
        self.MAX_POINTS = 100  # Максимальное количество точек на графике
        self.UPDATE_INTERVAL = 100  # Интервал обновления (мс)

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
        self.event_markers = []  # Хранит маркеры событий для каждого графика
        self.graph_name = ["МИДА-ДА-15 (Р1)", "МИДА-15 (Р2)", "СЕНСОР-МАГНЕТРОН (Р3)"]

        for i in range(3):
            # Создаём фигуру и оси
            fig = Figure(figsize=(8, 3))
            canvas = FigureCanvas(fig)
            ax = fig.add_subplot(111)

            # Настраиваем оси
            ax.yaxis.tick_right()
            ax.yaxis.set_label_position("right")
            ax.xaxis.set_visible(False)
            ax.set_title(self.graph_name[i])

            # Инициализируем линию графика
            line, = ax.plot([], [], color='blue')

            # Устанавливаем начальные границы
            ax.set_xlim(0, self.MAX_POINTS)
            ax.set_ylim(0, 100)  # Фиксированный масштаб по Y

            # Добавляем в списки
            self.figures.append(fig)
            self.canvases.append(canvas)
            self.axes.append(ax)
            self.lines.append(line)
            self.event_markers.append([])

            # Добавляем график в макет
            self.layout.addWidget(canvas)

            # Заполняем начальные данные
            for j in range(self.MAX_POINTS):
                self.timestamps[i].append(j)
                self.data[i].append(0)

            # Обновляем линию
            line.set_data(self.timestamps[i], self.data[i])

    def update_plots(self, actual_data):
        """Обновляет данные на всех трёх графиках."""
        for i in range(3):
            # Добавляем новые данные

            self.data[i].append(actual_data[i])
            self.timestamps[i].append(self.timestamps[i][-1] + 1 if self.timestamps[i] else 0)

            # Обновляем линию
            self.lines[i].set_data(self.timestamps[i], self.data[i])

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