"""Action tools: each write rule, the tau3 quirks, and that failed calls change nothing."""
import shutil

import pytest

from shop_db import store
from tools import action_tools as at
from tools.read_tools import get_order_details, get_user_details

PENDING = "#W6779827"     # ethan_lopez_6291, paid 4079.45 by gift_card_7219486 (balance 49.0)
DELIVERED = "#W3113816"   # emma_santos_9753, paid by credit_card_5869505; gift_card_6023546 (balance 36.0)
PROCESSED = "#W2611340"
ADDR = dict(address1="1 Main St", address2="", city="Austin", state="TX", country="USA", zip="73301")


@pytest.fixture(scope="module")
def clean_db(tmp_path_factory):
    if not store.SOURCE.exists():
        pytest.skip("run `uv run python -m shop_db.fetch` first")
    path = tmp_path_factory.mktemp("clean") / "shop.db"
    store.reset(path)
    return path


@pytest.fixture
def db(clean_db, tmp_path):
    """A fresh writable copy of the clean DB for each test."""
    path = tmp_path / "shop.db"
    shutil.copy(clean_db, path)
    conn = store.connect(path)
    yield conn
    conn.close()


def balance(conn, user, card):
    return get_user_details(conn, user)["payment_methods"][card]["balance"]


def assert_rejected(conn, fn, *args, match):
    before = store.export(conn)
    with pytest.raises(ValueError, match=match):
        fn(conn, *args)
    assert store.export(conn) == before  # nothing saved


# cancel
def test_cancel_refunds_gift_card_now(db):
    order = at.cancel_pending_order(db, PENDING, "no longer needed")
    assert order["status"] == "cancelled" and order["cancel_reason"] == "no longer needed"
    assert order["payment_history"][-1] == {"transaction_type": "refund", "amount": 4079.45, "payment_method_id": "gift_card_7219486"}
    assert balance(db, "ethan_lopez_6291", "gift_card_7219486") == 4128.45
    assert get_order_details(db, PENDING)["status"] == "cancelled"


def test_cancel_rules(db):
    assert_rejected(db, at.cancel_pending_order, PROCESSED, "no longer needed", match="Non-pending")
    assert_rejected(db, at.cancel_pending_order, PENDING, "too expensive", match="Invalid reason")
    assert_rejected(db, at.cancel_pending_order, "#W0000000", "no longer needed", match="Order not found")


# modify pending items
def test_modify_items_charges_gift_card(db):
    order = at.modify_pending_order_items(db, PENDING, ["1323134954"], ["3020722515"], "gift_card_7219486")
    assert order["status"] == "pending (item modified)"
    item = next(i for i in order["items"] if i["item_id"] == "3020722515")
    assert item["price"] == 238.64
    assert order["payment_history"][-1]["transaction_type"] == "payment"
    assert order["payment_history"][-1]["amount"] == pytest.approx(1.69)
    assert balance(db, "ethan_lopez_6291", "gift_card_7219486") == 47.31


def test_modify_items_copies_tau3_last_variant_quirk(db):
    order = at.modify_pending_order_items(
        db, PENDING, ["1323134954", "6942241102"], ["3020722515", "3360679910"], "credit_card_9789590")
    prices = {i["item_id"]: i["price"] for i in order["items"]}
    assert prices["3020722515"] == prices["3360679910"] == 195.26  # both get the last variant's price


def test_modify_items_rules(db):
    f = at.modify_pending_order_items
    assert_rejected(db, f, PENDING, ["7896397433"], ["2444431651"], "gift_card_7219486", match="Insufficient gift card")
    assert_rejected(db, f, PENDING, ["7896397433"], ["8140269513"], "credit_card_9789590", match="not found or available")
    assert_rejected(db, f, PENDING, ["7896397433"], ["7896397433"], "credit_card_9789590", match="should be different")
    assert_rejected(db, f, PENDING, ["7896397433"], ["3020722515"], "credit_card_9789590", match="Variant not found")
    assert_rejected(db, f, PENDING, ["0000000000"], ["3020722515"], "credit_card_9789590", match="not found")
    assert_rejected(db, f, PENDING, ["7896397433"], [], "credit_card_9789590", match="should match")
    assert_rejected(db, f, PENDING, ["1323134954"], ["3020722515"], "paypal_0000000", match="Payment method not found")
    assert_rejected(db, f, PROCESSED, ["6469567736"], ["4579334072"], "gift_card_1725971", match="Non-pending")


def test_modify_items_only_once(db):
    at.modify_pending_order_items(db, PENDING, ["1323134954"], ["3020722515"], "credit_card_9789590")
    assert_rejected(db, at.modify_pending_order_items, PENDING, ["6942241102"], ["3360679910"],
                    "credit_card_9789590", match="Non-pending")


# modify payment / address
def test_modify_payment_refunds_old_gift_card(db):
    order = at.modify_pending_order_payment(db, PENDING, "credit_card_9789590")
    assert [p["transaction_type"] for p in order["payment_history"]] == ["payment", "payment", "refund"]
    assert balance(db, "ethan_lopez_6291", "gift_card_7219486") == 4128.45


def test_modify_payment_rules(db):
    assert_rejected(db, at.modify_pending_order_payment, PENDING, "gift_card_7219486", match="should be different")
    assert_rejected(db, at.modify_pending_order_payment, PROCESSED, "gift_card_1725971", match="Non-pending")


def test_modify_order_address_allowed_after_item_change(db):
    at.modify_pending_order_items(db, PENDING, ["1323134954"], ["3020722515"], "credit_card_9789590")
    order = at.modify_pending_order_address(db, PENDING, **ADDR)
    assert list(order["address"]) == ["address1", "address2", "city", "country", "state", "zip"]
    assert order["address"]["zip"] == "73301"
    assert_rejected(db, at.modify_pending_order_address, PROCESSED, *ADDR.values(), match="Non-pending")


def test_modify_user_address(db):
    assert at.modify_user_address(db, "ethan_lopez_6291", **ADDR)["address"]["city"] == "Austin"
    assert_rejected(db, at.modify_user_address, "nobody_1", *ADDR.values(), match="User not found")


# return / exchange
def test_return_sorted_items(db):
    order = at.return_delivered_order_items(db, DELIVERED, ["4843487907", "2206116040"], "credit_card_5869505")
    assert order["status"] == "return requested"
    assert order["return_items"] == ["2206116040", "4843487907"]


def test_return_to_gift_card_and_rules(db):
    f = at.return_delivered_order_items
    assert_rejected(db, f, PENDING, ["7896397433"], "gift_card_7219486", match="Non-delivered")
    assert_rejected(db, f, DELIVERED, ["0000000000"], "credit_card_5869505", match="Some item not found")
    assert_rejected(db, f, DELIVERED, ["2206116040", "2206116040"], "credit_card_5869505", match="Some item not found")
    assert_rejected(db, f, DELIVERED, ["2206116040"], "paypal_0000000", match="Payment method not found")
    assert f(db, DELIVERED, ["2206116040"], "gift_card_6023546")["return_payment_method_id"] == "gift_card_6023546"


def test_exchange(db):
    order = at.exchange_delivered_order_items(db, DELIVERED, ["6243148452"], ["7747408585"], "gift_card_6023546")
    assert order["status"] == "exchange requested"
    assert order["exchange_price_difference"] == 2.01
    assert balance(db, "emma_santos_9753", "gift_card_6023546") == 36.0  # charged later, not now


def test_exchange_rules(db):
    f = at.exchange_delivered_order_items
    assert_rejected(db, f, DELIVERED, ["4422467033"], ["2444431651"], "gift_card_6023546", match="Insufficient gift card")
    assert_rejected(db, f, DELIVERED, ["4422467033"], [], "credit_card_5869505", match="should match")
    assert_rejected(db, f, PENDING, ["7896397433"], ["2444431651"], "credit_card_9789590", match="Non-delivered")


def test_transfer(db):
    assert at.transfer_to_human_agents(db, "wants a refund to a new card") == "Transfer successful"
