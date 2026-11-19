import pytest

from shopcart import Inventory, OutOfStock


def test_reserve_and_release():
    inv = Inventory({"APL": 5})
    inv.reserve("APL", 3)
    assert inv.available("APL") == 2
    inv.release("APL", 1)
    assert inv.available("APL") == 3


def test_reserve_too_many():
    inv = Inventory({"APL": 2})
    with pytest.raises(OutOfStock) as exc:
        inv.reserve("APL", 3)
    assert exc.value.available == 2


def test_restock():
    inv = Inventory()
    inv.restock("BK1", 4)
    assert inv.available("BK1") == 4


def test_release_more_than_reserved():
    inv = Inventory({"APL": 5})
    inv.reserve("APL", 1)
    with pytest.raises(ValueError):
        inv.release("APL", 2)
