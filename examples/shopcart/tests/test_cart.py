import pytest

from shopcart import Cart, Catalog, Product, UnknownProduct


def test_add_accumulates(catalog):
    cart = Cart(catalog)
    cart.add("APL", 2)
    cart.add("APL")
    assert cart.quantity("APL") == 3
    assert cart.item_count == 3


def test_add_rejects_bad_quantity(catalog):
    cart = Cart(catalog)
    with pytest.raises(ValueError):
        cart.add("APL", 0)


def test_add_unknown_sku(catalog):
    with pytest.raises(UnknownProduct):
        Cart(catalog).add("NOPE")


def test_remove_partial_and_full(catalog):
    cart = Cart(catalog)
    cart.add("APL", 5)
    cart.remove("APL", 2)
    assert cart.quantity("APL") == 3
    cart.remove("APL")
    assert cart.is_empty()


def test_remove_missing_is_noop(catalog):
    cart = Cart(catalog)
    cart.remove("APL")
    assert cart.is_empty()


def test_subtotal_and_lines_sorted(catalog):
    cart = Cart(catalog)
    cart.add("HDP")
    cart.add("APL", 3)
    assert [p.sku for p, _ in cart.lines()] == ["APL", "HDP"]
    assert cart.subtotal_cents() == 3 * 120 + 4200


def test_catalog_rejects_negative_price():
    with pytest.raises(ValueError):
        Catalog().add(Product("X", "x", -1))


def test_catalog_by_category(catalog):
    assert [p.sku for p in catalog.by_category("food")] == ["APL"]
    assert len(catalog) == 3
