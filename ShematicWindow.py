import math

from PyQt5.QtCore import Qt, QPointF, pyqtSignal, QObject, QTimer, QRectF
from PyQt5.QtGui import QBrush, QColor, QPen, QFont, QPolygonF
from PyQt5.QtWidgets import QGraphicsRectItem, QGraphicsScene, QGraphicsView, QGraphicsEllipseItem, QGraphicsLineItem, \
    QGraphicsTextItem, QGraphicsPolygonItem

class ValveSymbol(QObject, QGraphicsPolygonItem):
    clicked = pyqtSignal(str, str)  # (имя, действие)

    def __init__(self, label, set, center_x, center_y, orientation='h'):
        QObject.__init__(self)
        QGraphicsPolygonItem.__init__(self)
        self.name = label
        self.center_x = center_x
        self.center_y = center_y
        self.orientation = orientation
        self.size = 20

        # состояние напрямую отражает состояние системы
        self.status = "closed"  # closed / waiting / open
        self._build_shape(label, set)

        # обработка кликов
        self.triangle1_item.setAcceptedMouseButtons(Qt.LeftButton)
        self.triangle2_item.setAcceptedMouseButtons(Qt.LeftButton)
        self.triangle1_item.mousePressEvent = self._on_click
        self.triangle2_item.mousePressEvent = self._on_click

        self.update_color()

    def _build_shape(self, label, set):
        size = self.size
        cx, cy = self.center_x, self.center_y

        if self.orientation == 'h':
            triangle1 = QPolygonF([QPointF(cx, cy),
                                   QPointF(cx - size, cy - size),
                                   QPointF(cx - size, cy + size)])
            triangle2 = QPolygonF([QPointF(cx, cy),
                                   QPointF(cx + size, cy - size),
                                   QPointF(cx + size, cy + size)])
        else:
            triangle1 = QPolygonF([QPointF(cx, cy),
                                   QPointF(cx - size, cy - size),
                                   QPointF(cx + size, cy - size)])
            triangle2 = QPolygonF([QPointF(cx, cy),
                                   QPointF(cx - size, cy + size),
                                   QPointF(cx + size, cy + size)])

        self.triangle1_item = QGraphicsPolygonItem(triangle1)
        self.triangle2_item = QGraphicsPolygonItem(triangle2)
        self.triangle1_item.setBrush(QBrush(QColor("gray")))
        self.triangle2_item.setBrush(QBrush(QColor("gray")))

        # подпись
        self.label_item = QGraphicsTextItem(label)
        font = QFont(); font.setBold(True)
        self.label_item.setFont(font)
        if set == "l":
            self.label_item.setPos(cx - size - 30, cy - 10)
        elif set == "r":
            self.label_item.setPos(cx + size, cy - 10)
        elif set == "t":
            self.label_item.setPos(cx - 10, cy - size - 30)
        else:
            self.label_item.setPos(cx - 10, cy + size + 30)

    def add_to_scene(self, scene):
        scene.addItem(self.triangle1_item)
        scene.addItem(self.triangle2_item)
        scene.addItem(self.label_item)

    def _on_click(self, event):
        if self.status == "closed":
            self.status = "waiting"
            self.update_color()
            self.clicked.emit(self.name, "open")

        elif self.status == "open":
            self.status = "waiting"
            self.update_color()
            self.clicked.emit(self.name, "close")

    def update_color(self, status=None):
        """Обновление цвета элемента из Engine"""
        if status:
            self.status = status
        color_map = {
            "closed": "gray",
            "waiting": "yellow",
            "open": "lime"
        }
        color = QColor(color_map.get(self.status, "gray"))
        self.triangle1_item.setBrush(QBrush(color))
        self.triangle2_item.setBrush(QBrush(color))

    def apply_system_state(self, is_open: bool):
        """
        Вызывается ТОЛЬКО из Engine/MainWindow,
        когда пришло реальное состояние от устройства
        """
        new_status = "open" if is_open else "closed"

        if self.status != new_status:
            self.status = new_status
            self.update_color()

class PumpSymbol(QGraphicsRectItem):
    clicked = pyqtSignal(str, str)  # (имя, действие)

    def __init__(self, name, center_x, center_y):
        size = 40
        super().__init__(center_x - size / 2, center_y - size / 2, size, size)
        self.name = name
        self.status = "closed"
        self.command_queue = []
        self.size = size

        self.circle = QGraphicsEllipseItem(center_x - size / 4, center_y - size / 4, size / 2, size / 2)
        self.label_item = QGraphicsTextItem(name)
        font = QFont(); font.setBold(True)
        self.label_item.setFont(font)
        self.label_item.setPos(center_x - size - 5, center_y - 10)

        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.mousePressEvent = self._on_click
        self.update_color()

    def add_to_scene(self, scene):
        scene.addItem(self)
        scene.addItem(self.circle)
        scene.addItem(self.label_item)

    def update_color(self):
        color_map = {
            "closed": QColor("gray"),
            "waiting": QColor("yellow"),
            "open": QColor("lime")
        }
        self.setBrush(QBrush(color_map[self.status]))
        self.circle.setBrush(QBrush(color_map[self.status]))

    def _on_click(self, event):
        next_cmd = None
        if self.status == "closed":
            next_cmd = "open"
            self.status = "waiting"
        elif self.status == "open":
            next_cmd = "closed"
            self.status = "waiting"

        self.update_color()

    def apply_system_state(self, is_open: bool):
        """
        Вызывается ТОЛЬКО из Engine/MainWindow,
        когда пришло реальное состояние от устройства
        """
        new_status = "open" if is_open else "closed"

        if self.status != new_status:
            self.status = new_status
            self.update_color()

class VacuumGauge:
    def __init__(self, name, set, center_x, center_y, radius=15):
        self.center_x = center_x
        self.center_y = center_y
        self.radius = radius

        self.circle = QGraphicsEllipseItem(center_x - radius, center_y - radius, 2 * radius, 2 * radius)
        self.circle.setPen(QPen(Qt.black, 2))
        self.circle.setBrush(QBrush(QColor("white")))

        self.arrow = QGraphicsLineItem()
        self.arrow.setPen(QPen(Qt.red, 2))
        self.set_angle(0)

        self.label = QGraphicsTextItem(name)
        font = QFont()
        font.setBold(True)
        self.label.setFont(font)
        if set == "l":
            label_x = center_x - radius - 30
            label_y = center_y - 10
        elif set == "r":
            label_x = center_x + radius + 30
            label_y = center_y - 10
        elif set == "t":
            label_x = center_x - 10
            label_y = center_y - radius - 30
        else:
            label_x = center_x - 10
            label_y = center_y + radius + 30
        self.label.setPos(label_x, label_y)

    def set_angle(self, angle_deg):
        angle_rad = math.radians(angle_deg)
        end_x = self.center_x + self.radius * math.cos(angle_rad)
        end_y = self.center_y - self.radius * math.sin(angle_rad)
        self.arrow.setLine(self.center_x, self.center_y, end_x, end_y)

    def add_to_scene(self, scene):
        scene.addItem(self.circle)
        scene.addItem(self.arrow)
        scene.addItem(self.label)

class SchematicWidget(QGraphicsView):
    valve_command = pyqtSignal(str, str)  # к Engine

    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setSceneRect(0, 0, 400, 400)
        self.items = {}

        # очередь команд для имитации click (не обязательно Engine)
        self.command_queue = []
        self.processing = False

        # таймер для имитации последовательной обработки очереди
        self.timer = QTimer()
        self.timer.timeout.connect(self._process_next)
        self.timer.start(200)

        self._build_scene()

    def _build_scene(self):
        # Насосы
        self.items["NR"] = PumpSymbol("NR", 60, 220)
        self.items["NR"].add_to_scene(self.scene)
        self.items["NI"] = PumpSymbol("NI", 140, 480)
        self.items["NI"].add_to_scene(self.scene)

        # Клапаны
        for st, name, cx, cy, orient in [("l","V1",140,440,'v'), ("l","V2",60,180,'v'),
                                     ("l","V3",60,260,'v'), ("t","V4",180,100,'h'),
                                     ("r","V5",140,140,'v'), ("t","V6",20,20,'v'),
                                     ("t","V7",100,20,'v'), ("t","V8",260,100,'h'),
                                     ("t","VF",300,100,'h')]:
            valve = ValveSymbol(name, st, cx, cy, orient)
            valve.add_to_scene(self.scene)
            valve.clicked.connect(self._on_valve_clicked)
            self.items[name] = valve

        # Вакуумные датчики
        self.items["P1"] = VacuumGauge("P1", "t", 180, 400)
        self.items["P1"].add_to_scene(self.scene)
        self.items["P2"] = VacuumGauge("P2", "t", 220, 100)
        self.items["P2"].add_to_scene(self.scene)
        self.items["P3"] = VacuumGauge("P3", "t", 140, 60)
        self.items["P3"].add_to_scene(self.scene)

        self.items["CV1"] = QGraphicsRectItem(0, 40, 120, 120)
        self.items["CV1"].setBrush(QBrush(QColor("lightblue")))
        self.scene.addItem(self.items["CV1"])

        # подпись внутри фигуры CV1
        cv1_label = QGraphicsTextItem("CV1")
        font = QFont()
        font.setBold(True)
        cv1_label.setFont(font)

        rect = self.items["CV1"].rect()
        text_rect = cv1_label.boundingRect()
        cv1_label.setPos(
            rect.center().x() - text_rect.width() / 2,
            rect.center().y() - text_rect.height() / 2
        )
        self.scene.addItem(cv1_label)
        self.draw_line(60, 280, 60, 400)
        self.draw_line(160, 400, 60, 400)
        self.draw_line(140, 420, 140, 160)
        self.draw_line(140, 80, 140, 120)
        self.draw_line(120, 100, 160, 100)
        self.draw_square(-10, -30, 340, 320)
        self.draw_square(-10, 360, 340, 150)

    def draw_square(self, x, y, width, height):
        rect = QRectF(x, y, width, height)
        item = self.scene.addRect(rect)

        pen = QPen(Qt.red)
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        item.setPen(pen)  # было rect.setPen(pen)
        item.setBrush(QBrush(Qt.NoBrush))


    def draw_line(self, x1, y1, x2, y2):
        line = self.scene.addLine(x1, y1, x2, y2)
        pen = QPen(Qt.red)
        pen.setWidth(1)
        line.setPen(pen)

    def _on_valve_clicked(self, name: str, action: str):
        """Обрабатываем клик на элементе, просто кидаем сигнал"""
        self.valve_command.emit(name, action)

    def _process_next(self):
        """Обработка очереди кликов (для плавного UX, не обязательно)"""
        if not self.command_queue or self.processing:
            return
        self.processing = True
        name, action = self.command_queue.pop(0)
        self.valve_command.emit(name, action)
        self.processing = False

    # ------------------- обновление цветов -------------------
    def update_states(self, states: dict):
        """
        Обновление состояния всех клапанов и насосов по данным от Engine.
        states = {"V1": "open", "V2": "waiting", "V3": "closed", "NR": "on", ...}
        """
        for name, state in states.items():
            item = self.items.get(name)
            if not item:
                continue
            if hasattr(item, "update_color"):
                item.update_color(state)


