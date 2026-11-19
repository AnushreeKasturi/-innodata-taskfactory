"""Tax, shipping and order totals. All amounts are integer cents."""
from __future__ import annotations

from .cart import Cart

TAX_RATES_BPS = {"general": 1800, "food": 500, "books": 0}  # basis points
DEFAULT_TAX_BPS = 1800
SHIPPING_CENTS = 499
FREE_SHIPPING_THRESHOLD_CENTS = 5000


def _round_half_up(numerator: int, denominator: int) -> int:
    return (numerator * 2 + denominator) // (denominator * 2)


def tax_cents(cart: Cart) -> int:
    total = 0
    for product, qty in cart.lines():
        rate = TAX_RATES_BPS.get(product.category, DEFAULT_TAX_BPS)
        total += _round_half_up(product.price_cents * qty * rate, 10_000)
    return total


def shipping_cents(cart: Cart) -> int:
    if cart.is_empty() or cart.subtotal_cents() >= FREE_SHIPPING_THRESHOLD_CENTS:
        return 0
    return SHIPPING_CENTS


def total_cents(cart: Cart) -> int:
    return cart.subtotal_cents() + tax_cents(cart) + shipping_cents(cart)
