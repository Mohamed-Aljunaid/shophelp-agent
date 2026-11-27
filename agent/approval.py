"""Human approval for large refunds: which calls need staff sign-off, and for how much."""
import sqlite3

from shop_db import store


def refund_amount(conn: sqlite3.Connection, name: str, args: dict) -> float:
    """Money a write call would refund to the customer (0 if none or unknown)."""
    # shortcut: covers cancel and return; refunds from price differences (exchange/modify items) are not gated.
    order = store.get(conn, "orders", args.get("order_id", ""))
    if order is None:
        return 0.0
    if name == "cancel_pending_order":
        return round(sum(p["amount"] for p in order["payment_history"] if p["transaction_type"] == "payment"), 2)
    if name == "return_delivered_order_items":
        prices, total = [i for i in order["items"]], 0.0
        for item_id in args.get("item_ids", []):
            item = next((i for i in prices if i["item_id"] == item_id), None)
            if item:
                prices.remove(item)  # duplicates: each id counts one matching item
                total += item["price"]
        return round(total, 2)
    return 0.0
