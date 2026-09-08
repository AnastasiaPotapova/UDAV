"""
Форматирование измеренных значений температуры для строки под давлениями
(см. MainWindow._build_temperatures_bar).

В отличие от давлений (см. pressure_format.py), для температур в ТЗ не
задан особый формат научной нотации - каналы temperature_channel_1/2 и
temperature_mcu_internal/external из exchange_packet (protocol.json)
приходят как обычные uint16 в градусах Цельсия, поэтому выводим их как
есть, с суффиксом "°C", и "—" для отсутствующего/невалидного значения.
"""
import math

MISSING = "—"


def format_temperature(value, unit: str = "°C") -> str:
    """Форматирует значение температуры для строки нижней панели.

    value - число (°C) или None/невалидное значение (тогда возвращается "—")
    """
    if value is None:
        return MISSING
    try:
        value = float(value)
    except (TypeError, ValueError):
        return MISSING

    if math.isnan(value) or math.isinf(value):
        return MISSING

    if value == int(value):
        text = f"{int(value)}"
    else:
        text = f"{value:.1f}".replace(".", ",")

    if unit:
        text = f"{text} {unit}"
    return text
