"""Shared fixtures: a fresh shop database per test module."""
import pytest

from shop_db import store


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    """Read-only tests share one fresh DB per module."""
    if not store.SOURCE.exists():
        pytest.skip("run `uv run python -m shop_db.fetch` first")
    path = tmp_path_factory.mktemp("db") / "shop.db"
    store.reset(path)
    c = store.connect(path)
    yield c
    c.close()
