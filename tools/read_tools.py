"""Read-only shop tools, matching the tau3-bench retail tools.

Each tool takes an open sqlite3 connection first. Errors are raised as
ValueError with a message the agent can show or act on.
"""
import ast
import json
import operator
import sqlite3
import unicodedata

from shop_db import store


def _fold(text: str) -> str:
    """Fold accents and case for name/email matching (same as tau3 fold_for_match)."""
    decomposed = unicodedata.normalize("NFD", text.strip())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _unique(matches: list[str]) -> str:
    if len(matches) == 1:
        return matches[0]
    raise ValueError("User lookup is ambiguous" if matches else "User not found")


def find_user_id_by_email(conn: sqlite3.Connection, email: str) -> str:
    """Find a user id by email. Use this first to authenticate the user."""
    wanted = _fold(email)
    users = store.all_records(conn, "users")
    return _unique([uid for uid, u in users.items() if _fold(u["email"]) == wanted])


def find_user_id_by_name_zip(conn: sqlite3.Connection, first_name: str, last_name: str, zip: str) -> str:
    """Find a user id by first name, last name and zip code. Use only if the user
    cannot be found by email or does not remember their email."""
    first, last = _fold(first_name), _fold(last_name)
    users = store.all_records(conn, "users")
    return _unique([
        uid for uid, u in users.items()
        if _fold(u["name"]["first_name"]) == first
        and _fold(u["name"]["last_name"]) == last
        and u["address"]["zip"] == zip
    ])


def _get(conn: sqlite3.Connection, table: str, record_id: str, label: str) -> dict:
    record = store.get(conn, table, record_id)
    if record is None:
        raise ValueError(f"{label} not found")
    return record


def get_user_details(conn: sqlite3.Connection, user_id: str) -> dict:
    """Get a user's profile, payment methods and order ids, e.g. user_id 'sara_doe_496'."""
    return _get(conn, "users", user_id, "User")


def get_order_details(conn: sqlite3.Connection, order_id: str) -> dict:
    """Get the status and details of an order. Order ids start with '#', e.g. '#W0000000'."""
    return _get(conn, "orders", order_id, "Order")


def get_product_details(conn: sqlite3.Connection, product_id: str) -> dict:
    """Get a product and all its variant items. Product ids differ from item ids."""
    return _get(conn, "products", product_id, "Product")


def get_item_details(conn: sqlite3.Connection, item_id: str) -> dict:
    """Get one variant item (options, availability, price) by item id."""
    for product in store.all_records(conn, "products").values():
        if item_id in product["variants"]:
            return product["variants"][item_id]
    raise ValueError("Item not found")


def list_all_product_types(conn: sqlite3.Connection) -> str:
    """List all 50 product types as a JSON string {name: product_id}, sorted by name."""
    products = store.all_records(conn, "products").values()
    return json.dumps({p["name"]: p["product_id"] for p in products}, sort_keys=True)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    raise ValueError("Invalid expression")


def calculate(conn: sqlite3.Connection, expression: str) -> str:
    """Calculate a math expression with numbers, + - * /, parentheses and spaces.
    Returns the result rounded to 2 decimals."""
    # Parse instead of eval: blocks '**' and anything but plain arithmetic.
    if not all(ch in "0123456789+-*/(). " for ch in expression):
        raise ValueError("Invalid characters in expression")
    try:
        result = _eval(ast.parse(expression, mode="eval").body)
    except (SyntaxError, ZeroDivisionError) as exc:
        raise ValueError("Invalid expression") from exc
    return str(round(float(result), 2))
