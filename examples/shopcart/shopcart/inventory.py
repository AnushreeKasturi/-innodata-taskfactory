"""Stock levels and reservations."""
from __future__ import annotations


class OutOfStock(Exception):
    def __init__(self, sku: str, requested: int, available: int) -> None:
        super().__init__(f"{sku}: requested {requested}, available {available}")
        self.sku = sku
        self.requested = requested
        self.available = available


class Inventory:
    def __init__(self, stock: dict[str, int] | None = None) -> None:
        self._stock: dict[str, int] = dict(stock or {})
        self._reserved: dict[str, int] = {}

    def available(self, sku: str) -> int:
        return self._stock.get(sku, 0) - self._reserved.get(sku, 0)

    def restock(self, sku: str, qty: int) -> None:
        if qty <= 0:
            raise ValueError("quantity must be positive")
        self._stock[sku] = self._stock.get(sku, 0) + qty

    def reserve(self, sku: str, qty: int) -> None:
        if qty <= 0:
            raise ValueError("quantity must be positive")
        if qty > self.available(sku):
            raise OutOfStock(sku, qty, self.available(sku))
        self._reserved[sku] = self._reserved.get(sku, 0) + qty

    def release(self, sku: str, qty: int) -> None:
        held = self._reserved.get(sku, 0)
        if qty <= 0 or qty > held:
            raise ValueError("cannot release more than reserved")
        self._reserved[sku] = held - qty
