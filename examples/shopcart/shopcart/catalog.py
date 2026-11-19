"""Product catalog."""
from __future__ import annotations

from dataclasses import dataclass


class UnknownProduct(KeyError):
    """Raised when a SKU is not in the catalog."""


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price_cents: int
    category: str = "general"


class Catalog:
    def __init__(self) -> None:
        self._products: dict[str, Product] = {}

    def add(self, product: Product) -> None:
        if product.price_cents < 0:
            raise ValueError("price must be non-negative")
        self._products[product.sku] = product

    def get(self, sku: str) -> Product:
        try:
            return self._products[sku]
        except KeyError:
            raise UnknownProduct(sku) from None

    def by_category(self, category: str) -> list[Product]:
        return sorted(
            (p for p in self._products.values() if p.category == category),
            key=lambda p: p.sku,
        )

    def __len__(self) -> int:
        return len(self._products)
