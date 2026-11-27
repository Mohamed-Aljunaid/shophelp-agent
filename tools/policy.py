"""Policy checks enforced in code, on top of the tau3 tools.

The tau3 tools check order status, items and payment methods, but not *who*
is asking. A ShopSession is one conversation: every account tool needs an
authenticated user, and only that user's profile and orders can be touched.
The agent calls tools only through ShopSession.call.
"""
import sqlite3

from tools import action_tools, read_tools
from tools.read_tools import _get

TOOLS = {
    name: getattr(module, name)
    for module, names in [
        (read_tools, ["find_user_id_by_email", "find_user_id_by_name_zip", "get_user_details",
                      "get_order_details", "get_product_details", "get_item_details",
                      "list_all_product_types", "calculate"]),
        (action_tools, ["cancel_pending_order", "exchange_delivered_order_items",
                        "modify_pending_order_address", "modify_pending_order_items",
                        "modify_pending_order_payment", "modify_user_address",
                        "return_delivered_order_items", "transfer_to_human_agents"]),
    ]
    for name in names
}
AUTH_TOOLS = {"find_user_id_by_email", "find_user_id_by_name_zip"}
OPEN_TOOLS = {"calculate", "transfer_to_human_agents"}  # usable before authentication


class ShopSession:
    """One conversation with one customer."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.user_id: str | None = None

    def call(self, name: str, **args):
        """Run a tool by name after the policy checks. Raises ValueError if blocked."""
        if name not in TOOLS:
            raise ValueError(f"Unknown tool: {name}")
        if name not in AUTH_TOOLS | OPEN_TOOLS:
            if self.user_id is None:
                raise ValueError("Authenticate the user first (email, or name + zip code)")
            self._check_owner(args)
        result = TOOLS[name](self.conn, **args)
        if name in AUTH_TOOLS:
            if self.user_id not in (None, result):
                raise ValueError("You can only help one user per conversation")
            self.user_id = result
        return result

    def _check_owner(self, args: dict) -> None:
        """The user_id or order_id in the call must belong to the authenticated user."""
        if "user_id" in args and args["user_id"] != self.user_id:
            raise ValueError("You can only access the authenticated user's account")
        if "order_id" in args:
            order = _get(self.conn, "orders", args["order_id"], "Order")
            if order["user_id"] != self.user_id:
                raise ValueError("Order not found")  # don't reveal other users' orders exist
