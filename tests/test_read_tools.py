"""Read-only tools: lookups, not-found errors and the safe calculator."""
import json

import pytest

from tools import read_tools as rt


def test_find_user_by_email_folds_case(conn):
    assert rt.find_user_id_by_email(conn, " Noah.Brown7922@EXAMPLE.com") == "noah_brown_6181"
    with pytest.raises(ValueError, match="User not found"):
        rt.find_user_id_by_email(conn, "nobody@example.com")


def test_find_user_by_name_zip(conn):
    assert rt.find_user_id_by_name_zip(conn, "yusuf", "ROSSI", "19122") == "yusuf_rossi_9620"
    with pytest.raises(ValueError, match="User not found"):
        rt.find_user_id_by_name_zip(conn, "Yusuf", "Rossi", "00000")


def test_get_details(conn):
    assert rt.get_user_details(conn, "yusuf_rossi_9620")["user_id"] == "yusuf_rossi_9620"
    assert rt.get_order_details(conn, "#W2611340")["status"] == "processed"
    product = rt.get_product_details(conn, "9523456873")
    assert product["name"] == "T-Shirt"
    assert rt.get_item_details(conn, "9612497925")["options"]["size"] == "M"


@pytest.mark.parametrize("fn,arg,msg", [
    (rt.get_user_details, "nobody_1", "User not found"),
    (rt.get_order_details, "W2611340", "Order not found"),  # missing '#'
    (rt.get_product_details, "9612497925", "Product not found"),  # item id, not product id
    (rt.get_item_details, "9523456873", "Item not found"),  # product id, not item id
])
def test_not_found(conn, fn, arg, msg):
    with pytest.raises(ValueError, match=msg):
        fn(conn, arg)


def test_list_all_product_types(conn):
    types = json.loads(rt.list_all_product_types(conn))
    assert len(types) == 50 and types["T-Shirt"] == "9523456873"
    assert list(types) == sorted(types)


@pytest.mark.parametrize("expr", [
    "3131.1 + 4777.75 + 367.38", "155.33 - 147.05 + 268.77 - 235.13", "135.24 - 153.23",
    "(2 + 3) * 4 / 3", "-5 + 2",
])
def test_calculate_matches_eval(conn, expr):
    assert rt.calculate(conn, expr) == str(round(float(eval(expr)), 2))


@pytest.mark.parametrize("expr", ["9**9**9", "__import__('os')", "1/0", "2 +", "1 // 2"])
def test_calculate_rejects(conn, expr):
    with pytest.raises(ValueError):
        rt.calculate(conn, expr)
