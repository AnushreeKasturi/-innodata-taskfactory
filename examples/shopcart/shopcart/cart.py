"""Shopping cart."""
from __future__ import annotations

from .catalog import Catalog, Product


class Cart:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._lines: dict[str, int] = {}

    def add(self, sku: str, qty: int = 1) -> None:
        if qty <= 0:
            raise ValueError("quantity must be positive")
        self._catalog.get(sku)  # raises UnknownProduct
        self._lines[sku] = self._lines.get(sku, 0) + qty

    def remove(self, sku: str, qty: int | None = None) -> None:
        if sku not in self._lines:
            return
        if qty is None or qty >= self._lines[sku]:
            del self._lines[sku]
        else:
            self._lines[sku] -= qty

    def lines(self) -> list[tuple[Product, int]]:
        return [(self._catalog.get(sku), qty) for sku, qty in sorted(self._lines.items())]

    def quantity(self, sku: str) -> int:
        return self._lines.get(sku, 0)

    @property
    def item_count(self) -> int:
        return sum(self._lines.values())

    def subtotal_cents(self) -> int:
        return sum(p.price_cents * qty for p, qty in self.lines())

    def is_empty(self) -> bool:
        return not self._lines
