"""SQLite store: reset loads tau3 data, export round-trips exactly, reset undoes changes."""
import json

import pytest

from shop_db import store

pytestmark = pytest.mark.skipif(not store.SOURCE.exists(), reason="run `uv run python -m shop_db.fetch` first")


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "shop.db"
    store.reset(path)
    conn = store.connect(path)
    yield path, conn
    conn.close()


def test_export_matches_source_exactly(db):
    _, conn = db
    source = json.loads(store.SOURCE.read_text(encoding="utf-8"))
    assert store.export(conn) == source


def test_get_and_missing(db):
    _, conn = db
    assert store.get(conn, "users", "noah_brown_6181")["email"] == "noah.brown7922@example.com"
    assert store.get(conn, "orders", "#nope") is None
    with pytest.raises(ValueError):
        store.get(conn, "users; DROP TABLE users", "x")


def test_put_missing_record_raises(db):
    _, conn = db
    with pytest.raises(KeyError):
        store.put(conn, "orders", "#nope", {})


def test_reset_restores_clean_state(db):
    path, conn = db
    order = store.get(conn, "orders", "#W2611340")
    order["status"] = "cancelled"
    store.put(conn, "orders", "#W2611340", order)
    conn.commit()
    conn.close()

    store.reset(path)
    with store.connect(path) as fresh:
        assert store.get(fresh, "orders", "#W2611340")["status"] == "processed"
    fresh.close()
