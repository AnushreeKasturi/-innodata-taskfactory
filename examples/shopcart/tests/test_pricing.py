from shopcart import Cart
from shopcart.pricing import shipping_cents, tax_cents, total_cents


def test_tax_by_category(catalog):
    cart = Cart(catalog)
    cart.add("APL", 3)  # food 5%
    cart.add("BK1")  # books 0%
    assert tax_cents(cart) == 18


def test_tax_general(catalog):
    cart = Cart(catalog)
    cart.add("HDP")
    assert tax_cents(cart) == 756


def test_shipping_charged_below_threshold(catalog):
    cart = Cart(catalog)
    cart.add("BK1")
    assert shipping_cents(cart) == 499


def test_shipping_free_above_threshold(catalog):
    cart = Cart(catalog)
    cart.add("HDP")
    cart.add("BK1")
    assert shipping_cents(cart) == 0


def test_empty_cart_has_no_shipping(catalog):
    assert shipping_cents(Cart(catalog)) == 0
    assert total_cents(Cart(catalog)) == 0


def test_totals(catalog):
    cart = Cart(catalog)
    cart.add("APL", 3)
    cart.add("BK1")
    assert total_cents(cart) == 1860 + 18 + 499

    big = Cart(catalog)
    big.add("HDP")
    big.add("BK1")
    assert total_cents(big) == 5700 + 756
