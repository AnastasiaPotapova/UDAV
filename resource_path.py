import sys
import os


def resource_path(relative_path: str) -> str:
    """
    Возвращает абсолютный путь к ресурсу, работает как при запуске
    из исходников, так и из собранного PyInstaller .exe.
    """
    if hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)