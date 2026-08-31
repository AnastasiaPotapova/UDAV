"""
Форматирование измеренных значений давления в нотацию вида "100,00E-2",
принятую в ТЗ (см. Протокол/ТЗ_К_ПО.docx, п.3):

    Р1, Р3, Р стат. — мантисса из 3 целых цифр и обязательно 2 знака
                       после запятой:   "100,00E-2"
    Р2              — мантисса из 4 целых цифр, без дробной части:
                       "1000E-1"

Число всегда представляется как mantissa * 10**exp, где количество
целых разрядов мантиссы фиксировано (leading_digits), а запятая -
русская (не точка).
"""
import math

MISSING = "—"


def format_pressure(value, leading_digits: int = 3, decimals: int = 2) -> str:
    """Форматирует давление (в Паскалях) в нотацию "ХХХ,ХХEN".

    value           - число (Па) или None/невалидное значение
    leading_digits  - сколько целых цифр должно быть у мантиссы (3 или 4)
    decimals        - сколько знаков после запятой у мантиссы (0 или 2)
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

    return f"{mantissa_str}E{exp}"


def format_p1(value) -> str:
    """Р1 - датчик МИДА-ДА-15, формат '100,00E-2'."""
    return format_pressure(value, leading_digits=3, decimals=2)


def format_p2(value) -> str:
    """Р2 - датчик МИДА-15, формат '1000E-1'."""
    return format_pressure(value, leading_digits=4, decimals=0)


def format_p3(value) -> str:
    """Р3 - СЕНСОР-МАГНЕТРОН, формат '100,00E-2'."""
    return format_pressure(value, leading_digits=3, decimals=2)


def format_pstat(value) -> str:
    """Р стат. - давление после статического расширения, формат '100,00E-2'."""
    return format_pressure(value, leading_digits=3, decimals=2)
