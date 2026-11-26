"""Check the fetched tau3-bench retail files have the expected shape."""
import json

import pytest

from shop_db.fetch import DEST, FILES

pytestmark = pytest.mark.skipif(
    not all((DEST / f).exists() for f in FILES), reason="run `uv run python -m shop_db.fetch` first"
)


def test_db_counts():
    db = json.loads((DEST / "db.json").read_text(encoding="utf-8"))
    assert {k: len(v) for k, v in db.items()} == {"products": 50, "users": 500, "orders": 1000}


def test_task_splits():
    tasks = json.loads((DEST / "tasks.json").read_text(encoding="utf-8"))
    splits = json.loads((DEST / "split_tasks.json").read_text(encoding="utf-8"))
    ids = {t["id"] for t in tasks}
    assert len(tasks) == 114
    assert set(splits["test"]) <= ids and len(splits["test"]) == 40
