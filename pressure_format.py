"""
Форматирование измеренных значений давления в нотацию вида "100,00E-2",
принятую в ТЗ (см. Протокол/ТЗ_К_ПО.docx, п.3):

    Все давления (Р1, Р2, Р3, Р стат.) — мантисса из 1 целой цифры и
    3 знаков после запятой:   "1,234E-2"

Число всегда представляется как mantissa * 10**exp, где количество
целых разрядов мантиссы фиксировано (leading_digits), а запятая -
русская (не точка).

По ТЗ_к_ПО_2.docx, п.5, единица измерения "Па" обязательно указывается
после каждого из значений Р1, Р2, Р3, Р стат. — этим занимается параметр
unit ниже (единый источник форматирования и для нижней строки значений,
и для подписи текущего значения на графике).
"""
import math

MISSING = "—"


def format_pressure(value, leading_digits: int = 3, decimals: int = 2, unit: str = "") -> str:
    """Форматирует давление (в Паскалях) в нотацию "ХХХ,ХХEN [ед.]".

    value           - число (Па) или None/невалидное значение
    leading_digits  - сколько целых цифр должно быть у мантиссы (3 или 4)
    decimals        - сколько знаков после запятой у мантиссы (0 или 2)
    unit            - единица измерения, добавляемая после значения
                       (ТЗ_к_ПО_2.docx, п.5); для MISSING не добавляется
    """
    if value is None:
        return MISSING
    try:
        value = float(value)
    except (TypeError, ValueError):
        return MISSING

    if math.isnan(value) or math.isinf(value):
        return MISSING

    if value == 0:
        mantissa, exp = 0.0, 0
    else:
        sign = -1 if value < 0 else 1
        magnitude = abs(value)
        k = math.floor(math.log10(magnitude))
        exp = k - (leading_digits - 1)
        mantissa = magnitude / (10 ** exp)
        mantissa = round(mantissa, decimals)

        # округление могло вытолкнуть мантиссу за верхнюю границу разряда
        # (например 999,996 -> 1000,00) - переносим на порядок выше
        upper = 10 ** leading_digits
        if mantissa >= upper:
            mantissa /= 10
            exp += 1

        mantissa *= sign

    if decimals == 0:
        mantissa_str = f"{mantissa:.0f}"
    else:
        mantissa_str = f"{mantissa:.{decimals}f}".replace(".", ",")

    result = f"{mantissa_str}E{exp}"
    if unit:
        result = f"{result} {unit}"
    return result


# Единый формат всех давлений (нижняя панель и подписи на графиках):
# одна цифра до запятой, три после и степень десяти: '1,234E-2 Па'.
# (Раньше было '100,00E-2' у Р1/Р3/Р стат. и '1000E-1' у Р2.)
PRESSURE_LEADING_DIGITS = 1
PRESSURE_DECIMALS = 3


def _format_unified(value) -> str:
    return format_pressure(value, leading_digits=PRESSURE_LEADING_DIGITS,
                           decimals=PRESSURE_DECIMALS, unit="Па")


def format_p1(value) -> str:
    """Р1 - датчик МИДА-ДА-15, формат '1,234E-2 Па'."""
    return _format_unified(value)


def format_p2(value) -> str:
    """Р2 - датчик МИДА-15, формат '1,234E-2 Па'."""
    return _format_unified(value)


def format_p3(value) -> str:
    """Р3 - СЕНСОР-МАГНЕТРОН, формат '1,234E-2 Па'."""
    return _format_unified(value)


def format_pstat(value) -> str:
    """Р стат. - давление после статического расширения, формат '1,234E-2 Па'."""
    return _format_unified(value)


def format_temperature(value, scale: float = 1.0) -> str:
    """Температура в °C, всегда с одним знаком после запятой (запятая -
    десятичный разделитель, как и у давлений в этом модуле).

    scale - контроллер отдаёт T MCU (внутр./внешн.) уже умноженными на 100
    и 10 соответственно, поэтому перед выводом их нужно поделить:
    format_temperature(raw, scale=100) для внутр., scale=10 для внешн. Для
    T1/T2 (процессные каналы) масштабирование не нужно, scale=1.0 по
    умолчанию."""
    if value is None:
        return MISSING
    try:
        value = float(value) / scale
    except (TypeError, ValueError, ZeroDivisionError):
        return MISSING
    if math.isnan(value) or math.isinf(value):
        return MISSING
    return f"{value:.1f} °C".replace(".", ",")