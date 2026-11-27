"""SQLite store for the shop data: one table per collection, each row a JSON record.

Keeping records as JSON lets us export back to the exact tau3 `db.json` shape,
which evaluation needs (it compares whole-DB hashes).

Reset to a clean state: uv run python -m shop_db.store
"""
import json
import sqlite3
from pathlib import Path

from config import settings
from shop_db.fetch import DEST

TABLES = ("users", "orders", "products")
SOURCE = DEST / "db.json"
DB_PATH = settings.db_path


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open the shop database."""
    return sqlite3.connect(path)


def reset(path: Path = DB_PATH, source: Path = SOURCE) -> None:
    """Rebuild the database from the tau3 db.json so every run starts from the same state."""
    data = json.loads(Path(source).read_text(encoding="utf-8"))
    with connect(path) as conn:
        for table in TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            conn.executemany(
                f"INSERT INTO {table} VALUES (?, ?)",
                ((key, json.dumps(rec)) for key, rec in data[table].items()),
            )
    conn.close()


def _check(table: str) -> None:
    if table not in TABLES:
        raise ValueError(f"unknown table: {table}")


def get(conn: sqlite3.Connection, table: str, record_id: str) -> dict | None:
    """Return one record as a dict, or None if it does not exist."""
    _check(table)
    row = conn.execute(f"SELECT data FROM {table} WHERE id = ?", (record_id,)).fetchone()
    return json.loads(row[0]) if row else None


def put(conn: sqlite3.Connection, table: str, record_id: str, record: dict) -> None:
    """Save (replace) one record. The caller commits."""
    _check(table)
    cur = conn.execute(f"UPDATE {table} SET data = ? WHERE id = ?", (json.dumps(record), record_id))
    if cur.rowcount == 0:
        raise KeyError(f"{table} record not found: {record_id}")


def all_records(conn: sqlite3.Connection, table: str) -> dict[str, dict]:
    """Return every record in a table, keyed by id, in insertion order."""
    _check(table)
    rows = conn.execute(f"SELECT id, data FROM {table} ORDER BY rowid")
    return {rid: json.loads(data) for rid, data in rows}


def export(conn: sqlite3.Connection) -> dict:
    """Return the whole database in the tau3 db.json shape."""
    return {table: all_records(conn, table) for table in TABLES}


if __name__ == "__main__":
    reset()
    print(f"reset {DB_PATH}")
