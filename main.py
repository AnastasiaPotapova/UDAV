from Engine import Engine

# Основной движок
engine = Engine()

import sys

from PyQt5.QtWidgets import QApplication

from MainWindow import MainWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)
    engine = Engine()
    main = MainWindow(engine)
    main.show()
    sys.exit(app.exec_())