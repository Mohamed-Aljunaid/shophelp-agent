"""Action (write) tools, matching the tau3-bench retail tools exactly.

Evaluation compares whole-DB hashes against tau3's own tools, so every write
here must produce the same data, including tau3's quirks (noted inline).
Each tool validates everything first, then saves in one transaction.
"""
import sqlite3

from shop_db import store
from tools.read_tools import _get

CANCEL_REASONS = ("no longer needed", "ordered by mistake")


def _is_gift_card(method: dict) -> bool:
    return method["source"] == "gift_card"


def _payment_method(user: dict, payment_method_id: str) -> dict:
    if payment_method_id not in user["payment_methods"]:
        raise ValueError("Payment method not found")
    return user["payment_methods"][payment_method_id]


def _check_items_in_order(order: dict, item_ids: list[str], message: str) -> None:
    """Each id (with duplicates) must appear at least as often in the order."""
    all_item_ids = [item["item_id"] for item in order["items"]]
    for item_id in item_ids:
        if item_ids.count(item_id) > all_item_ids.count(item_id):
            raise ValueError(message.format(item_id=item_id))


def _new_variants(conn, order: dict, item_ids: list[str], new_item_ids: list[str], forbid_same: bool):
    """Check each new item is an available variant of the same product; return (variants, price diff)."""
    if len(item_ids) != len(new_item_ids):
        raise ValueError("The number of items to be exchanged should match")
    variants, diff = [], 0
    for item_id, new_item_id in zip(item_ids, new_item_ids):
        if forbid_same and item_id == new_item_id:
            raise ValueError("The new item id should be different from the old item id")
        item = next(i for i in order["items"] if i["item_id"] == item_id)
        product = _get(conn, "products", item["product_id"], "Product")
        if new_item_id not in product["variants"]:
            raise ValueError("Variant not found")
        variant = product["variants"][new_item_id]
        if not variant["available"]:
            raise ValueError(f"New item {new_item_id} not found or available")
        variants.append(variant)
        diff += variant["price"] - item["price"]
    return variants, diff


def cancel_pending_order(conn: sqlite3.Connection, order_id: str, reason: str) -> dict:
    """Cancel a pending order. Reason must be 'no longer needed' or 'ordered by mistake'.
    Payments are refunded: gift cards immediately, other methods in 5-7 business days."""
    order = _get(conn, "orders", order_id, "Order")
    if order["status"] != "pending":
        raise ValueError("Non-pending order cannot be cancelled")
    if reason not in CANCEL_REASONS:
        raise ValueError("Invalid reason")
    user = _get(conn, "users", order["user_id"], "User")

    refunds = []
    for payment in order["payment_history"]:
        pid = payment["payment_method_id"]
        refunds.append({"transaction_type": "refund", "amount": payment["amount"], "payment_method_id": pid})
        method = _payment_method(user, pid)
        if _is_gift_card(method):
            method["balance"] = round(method["balance"] + payment["amount"], 2)

    order["status"] = "cancelled"
    order["cancel_reason"] = reason
    order["payment_history"].extend(refunds)
    with conn:
        store.put(conn, "users", user["user_id"], user)
        store.put(conn, "orders", order_id, order)
    return order


def exchange_delivered_order_items(
    conn: sqlite3.Connection, order_id: str, item_ids: list[str], new_item_ids: list[str], payment_method_id: str
) -> dict:
    """Exchange items of a delivered order for other available variants of the same product.
    Can only be done once per order. The payment method pays or receives the price difference."""
    order = _get(conn, "orders", order_id, "Order")
    if order["status"] != "delivered":
        raise ValueError("Non-delivered order cannot be exchanged")
    _check_items_in_order(order, item_ids, "Number of {item_id} not found.")
    _, diff = _new_variants(conn, order, item_ids, new_item_ids, forbid_same=False)
    diff = round(diff, 2)
    method = _payment_method(_get(conn, "users", order["user_id"], "User"), payment_method_id)
    if _is_gift_card(method) and method["balance"] < diff:
        raise ValueError("Insufficient gift card balance to pay for the price difference")

    order["status"] = "exchange requested"
    order["exchange_items"] = sorted(item_ids)
    order["exchange_new_items"] = sorted(new_item_ids)
    order["exchange_payment_method_id"] = payment_method_id
    order["exchange_price_difference"] = diff
    with conn:
        store.put(conn, "orders", order_id, order)
    return order


def _address(address1, address2, city, state, country, zip) -> dict:
    # Key order matches tau3's UserAddress model.
    return {"address1": address1, "address2": address2, "city": city, "country": country, "state": state, "zip": zip}


def modify_pending_order_address(
    conn: sqlite3.Connection, order_id: str, address1: str, address2: str, city: str, state: str, country: str, zip: str
) -> dict:
    """Change the shipping address of a pending order."""
    order = _get(conn, "orders", order_id, "Order")
    if "pending" not in order["status"]:  # tau3 allows 'pending (item modified)' here
        raise ValueError("Non-pending order cannot be modified")
    order["address"] = _address(address1, address2, city, state, country, zip)
    with conn:
        store.put(conn, "orders", order_id, order)
    return order


def modify_pending_order_items(
    conn: sqlite3.Connection, order_id: str, item_ids: list[str], new_item_ids: list[str], payment_method_id: str
) -> dict:
    """Swap items in a pending order for other available variants of the same product.
    Can only be called once per order. The payment method pays or receives the price difference."""
    order = _get(conn, "orders", order_id, "Order")
    if order["status"] != "pending":
        raise ValueError("Non-pending order cannot be modified")
    _check_items_in_order(order, item_ids, "{item_id} not found")
    variants, diff = _new_variants(conn, order, item_ids, new_item_ids, forbid_same=True)
    user = _get(conn, "users", order["user_id"], "User")
    method = _payment_method(user, payment_method_id)
    if _is_gift_card(method) and method["balance"] < diff:
        raise ValueError("Insufficient gift card balance to pay for the new item")

    # tau3 quirk: diff is stored unrounded, and a row is added even when diff is 0.
    order["payment_history"].append({
        "transaction_type": "payment" if diff > 0 else "refund",
        "amount": abs(diff),
        "payment_method_id": payment_method_id,
    })
    if _is_gift_card(method):
        method["balance"] = round(method["balance"] - diff, 2)

    # tau3 quirk: every changed item gets the price/options of the LAST new variant checked.
    last = variants[-1]
    for item_id, new_item_id in zip(item_ids, new_item_ids):
        item = next(i for i in order["items"] if i["item_id"] == item_id)
        item["item_id"] = new_item_id
        item["price"] = last["price"]
        item["options"] = dict(last["options"])
    order["status"] = "pending (item modified)"
    with conn:
        store.put(conn, "users", user["user_id"], user)
        store.put(conn, "orders", order_id, order)
    return order


def modify_pending_order_payment(conn: sqlite3.Connection, order_id: str, payment_method_id: str) -> dict:
    """Pay for a pending order with a different payment method; the old one is refunded."""
    order = _get(conn, "orders", order_id, "Order")
    if "pending" not in order["status"]:
        raise ValueError("Non-pending order cannot be modified")
    user = _get(conn, "users", order["user_id"], "User")
    method = _payment_method(user, payment_method_id)
    history = order["payment_history"]
    if len(history) != 1 or history[0]["transaction_type"] != "payment":
        raise ValueError("There should be exactly one payment for a pending order")
    old_id = history[0]["payment_method_id"]
    if old_id == payment_method_id:
        raise ValueError("The new payment method should be different from the current one")
    amount = history[0]["amount"]
    if _is_gift_card(method) and method["balance"] < amount:
        raise ValueError("Insufficient gift card balance to pay for the order")

    history.append({"transaction_type": "payment", "amount": amount, "payment_method_id": payment_method_id})
    history.append({"transaction_type": "refund", "amount": amount, "payment_method_id": old_id})
    if _is_gift_card(method):
        method["balance"] = round(method["balance"] - amount, 2)
    old_method = _payment_method(user, old_id)
    if _is_gift_card(old_method):
        old_method["balance"] = round(old_method["balance"] + amount, 2)
    with conn:
        store.put(conn, "users", user["user_id"], user)
        store.put(conn, "orders", order_id, order)
    return order


def modify_user_address(
    conn: sqlite3.Connection, user_id: str, address1: str, address2: str, city: str, state: str, country: str, zip: str
) -> dict:
    """Change a user's default address."""
    user = _get(conn, "users", user_id, "User")
    user["address"] = _address(address1, address2, city, state, country, zip)
    with conn:
        store.put(conn, "users", user_id, user)
    return user


def return_delivered_order_items(
    conn: sqlite3.Connection, order_id: str, item_ids: list[str], payment_method_id: str
) -> dict:
    """Request a return of items from a delivered order. The refund goes to the
    original payment method or a gift card. The user gets an email with return steps."""
    order = _get(conn, "orders", order_id, "Order")
    if order["status"] != "delivered":
        raise ValueError("Non-delivered order cannot be returned")
    method = _payment_method(_get(conn, "users", order["user_id"], "User"), payment_method_id)
    if not _is_gift_card(method) and payment_method_id != order["payment_history"][0]["payment_method_id"]:
        raise ValueError("Payment method should be the original payment method")
    _check_items_in_order(order, item_ids, "Some item not found")

    order["status"] = "return requested"
    order["return_items"] = sorted(item_ids)
    order["return_payment_method_id"] = payment_method_id
    with conn:
        store.put(conn, "orders", order_id, order)
    return order


def transfer_to_human_agents(conn: sqlite3.Connection, summary: str) -> str:
    """Hand the user to a human agent with a summary. Only if the user asks for a human
    or the request cannot be handled with the available tools."""
    return "Transfer successful"
