import pytest

from shopcart import Catalog, Product


@pytest.fixture
def catalog():
    c = Catalog()
    c.add(Product("APL", "Apple", 120, "food"))
    c.add(Product("BK1", "Novel", 1500, "books"))
    c.add(Product("HDP", "Headphones", 4200, "general"))
    return c
