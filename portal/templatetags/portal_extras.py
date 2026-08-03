from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def get_item(obj, key):
    """
    Позволява {{ row|get_item:col.key }} в темплейта.
    Работи и за dict, и за обекти с атрибути.
    """
    if obj is None or key is None:
        return ""

    # dict / mapping
    if hasattr(obj, "get"):
        try:
            return obj.get(key, "")
        except Exception:
            pass

    # fallback – атрибут
    try:
        return getattr(obj, key, "")
    except Exception:
        return ""


@register.filter(name="report_value")
def report_value(obj, key):
    """
    Alias за get_item, ползва се в reports.html:
      {{ row|report_value:col.key }}
    """
    return get_item(obj, key)


@register.filter
def is_portal_admin(user):
    return user.is_superuser or user.is_staff


# ---------------------------------------------------------------------------
# Currency / number presentation
#
# Figures on a cost platform have to read as money at a glance. A bare
# "1624335" forces the reader to count digits before they can react to it,
# which is the opposite of what a KPI is for.
# ---------------------------------------------------------------------------

REPORTING_CURRENCY = "EUR"

CURRENCY_SYMBOLS = {
    "EUR": "€",
    "USD": "$",
    "GBP": "£",
    "CHF": "CHF ",
    "BGN": "лв ",
}


def _to_decimal(value):
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


@register.filter
def money(value, currency=REPORTING_CURRENCY):
    """
    {{ hero_total_spend|money }}          -> €1,624,335
    {{ row.annual_value|money:"GBP" }}    -> £337,000
    """
    amount = _to_decimal(value)
    if amount is None:
        return "—"
    symbol = CURRENCY_SYMBOLS.get((currency or "").upper(), f"{currency} ")
    return f"{symbol}{amount:,.0f}"


@register.filter
def money_compact(value, currency=REPORTING_CURRENCY):
    """
    Shortened form for tight KPI tiles.
    1_624_335 -> €1.62M   ·   194_920 -> €195k
    """
    amount = _to_decimal(value)
    if amount is None:
        return "—"
    symbol = CURRENCY_SYMBOLS.get((currency or "").upper(), f"{currency} ")
    a = abs(amount)
    sign = "-" if amount < 0 else ""
    if a >= 1_000_000_000:
        return f"{sign}{symbol}{a / 1_000_000_000:.2f}B"
    if a >= 1_000_000:
        return f"{sign}{symbol}{a / 1_000_000:.2f}M"
    if a >= 1_000:
        return f"{sign}{symbol}{a / 1_000:.0f}k"
    return f"{sign}{symbol}{a:,.0f}"


@register.filter
def thousands(value):
    """Plain grouped integer, for counts rather than money."""
    amount = _to_decimal(value)
    if amount is None:
        return "—"
    return f"{amount:,.0f}"


@register.filter
def reporting_currency(_=None):
    """{{ ''|reporting_currency }} -> EUR"""
    return REPORTING_CURRENCY

# ---------------------------------------------------------------------------
# Currency presentation
# ---------------------------------------------------------------------------
from decimal import Decimal, InvalidOperation

REPORTING_CURRENCY = "EUR"
CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF ", "BGN": "лв "}


def _to_decimal(value):
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


@register.filter
def money(value, currency=REPORTING_CURRENCY):
    amount = _to_decimal(value)
    if amount is None:
        return "—"
    symbol = CURRENCY_SYMBOLS.get((currency or "").upper(), f"{currency} ")
    return f"{symbol}{amount:,.0f}"


@register.filter
def money_compact(value, currency=REPORTING_CURRENCY):
    amount = _to_decimal(value)
    if amount is None:
        return "—"
    symbol = CURRENCY_SYMBOLS.get((currency or "").upper(), f"{currency} ")
    a, sign = abs(amount), "-" if amount < 0 else ""
    if a >= 1_000_000:
        return f"{sign}{symbol}{a / 1_000_000:.2f}M"
    if a >= 1_000:
        return f"{sign}{symbol}{a / 1_000:.0f}k"
    return f"{sign}{symbol}{a:,.0f}"


@register.filter
def thousands(value):
    amount = _to_decimal(value)
    return "—" if amount is None else f"{amount:,.0f}"