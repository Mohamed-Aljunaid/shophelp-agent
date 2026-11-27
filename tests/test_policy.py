"""Policy layer: authenticate first, one user per conversation, own data only."""
import json
import shutil

import pytest

from shop_db import store
from tools.policy import TOOLS, ShopSession

ETHAN_ORDER = "#W6779827"   # pending, belongs to ethan_lopez_6291
OTHER_ORDER = "#W3113816"   # belongs to emma_santos_9753


@pytest.fixture(scope="module")
def clean_db(tmp_path_factory):
    if not store.SOURCE.exists():
        pytest.skip("run `uv run python -m shop_db.fetch` first")
    path = tmp_path_factory.mktemp("clean") / "shop.db"
    store.reset(path)
    return path


@pytest.fixture
def session(clean_db, tmp_path):
    path = tmp_path / "shop.db"
    shutil.copy(clean_db, path)
    conn = store.connect(path)
    yield ShopSession(conn)
    conn.close()


def login(s):
    user = store.get(s.conn, "users", "ethan_lopez_6291")
    assert s.call("find_user_id_by_email", email=user["email"]) == "ethan_lopez_6291"


def test_registry_has_all_16_tau3_tools():
    assert len(TOOLS) == 16 and "think" not in TOOLS  # tau3 has 'think' commented out


@pytest.mark.parametrize("name,args", [
    ("get_order_details", {"order_id": ETHAN_ORDER}),
    ("get_user_details", {"user_id": "ethan_lopez_6291"}),
    ("get_product_details", {"product_id": "9523456873"}),
    ("list_all_product_types", {}),
    ("cancel_pending_order", {"order_id": ETHAN_ORDER, "reason": "no longer needed"}),
])
def test_blocked_before_authentication(session, name, args):
    with pytest.raises(ValueError, match="Authenticate the user first"):
        session.call(name, **args)
    assert store.get(session.conn, "orders", ETHAN_ORDER)["status"] == "pending"


def test_open_tools_work_before_authentication(session):
    assert session.call("calculate", expression="1 + 2") == "3.0"
    assert session.call("transfer_to_human_agents", summary="cannot log in") == "Transfer successful"


def test_failed_lookup_does_not_authenticate(session):
    with pytest.raises(ValueError, match="User not found"):
        session.call("find_user_id_by_email", email="nobody@example.com")
    assert session.user_id is None


def test_own_order_allowed_after_login(session):
    login(session)
    assert session.call("get_order_details", order_id=ETHAN_ORDER)["user_id"] == "ethan_lopez_6291"
    assert session.call("cancel_pending_order", order_id=ETHAN_ORDER, reason="ordered by mistake")["status"] == "cancelled"


def test_other_users_data_blocked(session):
    login(session)
    with pytest.raises(ValueError, match="Order not found"):
        session.call("get_order_details", order_id=OTHER_ORDER)
    with pytest.raises(ValueError, match="authenticated user's account"):
        session.call("get_user_details", user_id="emma_santos_9753")
    before = store.export(session.conn)
    with pytest.raises(ValueError, match="Order not found"):
        session.call("return_delivered_order_items", order_id=OTHER_ORDER,
                     item_ids=["2206116040"], payment_method_id="credit_card_5869505")
    with pytest.raises(ValueError, match="authenticated user's account"):
        session.call("modify_user_address", user_id="emma_santos_9753", address1="x", address2="",
                     city="x", state="x", country="USA", zip="00000")
    assert store.export(session.conn) == before


def test_one_user_per_conversation(session):
    login(session)
    with pytest.raises(ValueError, match="one user per conversation"):
        session.call("find_user_id_by_name_zip", first_name="Emma", last_name="Santos",
                     zip=store.get(session.conn, "users", "emma_santos_9753")["address"]["zip"])
    assert session.user_id == "ethan_lopez_6291"
    login(session)  # same user again is fine


def test_unknown_tool(session):
    with pytest.raises(ValueError, match="Unknown tool"):
        session.call("delete_everything")


def test_gold_actions_pass_policy(clean_db, tmp_path):
    """Every write in every tau3 task works through the policy once its owner is logged in."""
    tasks = json.loads((store.SOURCE.parent / "tasks.json").read_text(encoding="utf-8"))
    for task in tasks:
        path = tmp_path / f"t{task['id']}.db"
        shutil.copy(clean_db, path)
        with store.connect(path) as conn:
            s = ShopSession(conn)
            for action in task["evaluation_criteria"]["actions"] or []:
                if s.user_id is None and action["name"] not in {"find_user_id_by_email", "find_user_id_by_name_zip"}:
                    s.user_id = task_owner(conn, action["arguments"])  # tasks omit the login step
                try:
                    s.call(action["name"], **action["arguments"])
                except ValueError:  # some gold lookups fail on purpose (wrong email/zip given)
                    with pytest.raises(ValueError):
                        TOOLS[action["name"]](conn, **action["arguments"])
        conn.close()


def task_owner(conn, args):
    if "order_id" in args:
        return store.get(conn, "orders", args["order_id"])["user_id"]
    return args.get("user_id")
