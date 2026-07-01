from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

register = template.Library()


@register.filter
def rupiah(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return "Rp 0"

    if amount <= 0:
        return "Gratis"

    formatted = f"{amount:,.0f}".replace(",", ".")
    return f"Rp {formatted}"


@register.filter
def rupiah_money(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return "Rp 0"

    formatted = f"{amount:,.0f}".replace(",", ".")
    return f"Rp {formatted}"
