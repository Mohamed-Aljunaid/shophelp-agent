# τ³-bench retail domain – study notes (step 2.1)

Source: [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench) (MIT), pinned at commit `768f3d8`.
The original `sierra-research/tau-bench` repo now warns that its retail tasks are outdated, so we use the corrected τ³-bench version.
Get the files with `uv run python -m shop_db.fetch` (saved to `data/tau2-retail/`, not committed). The policy is copied to `policy/retail_policy.md`.

## Files

| File | Contents |
|---|---|
| `db.json` (2.8 MB) | `{"products": 50, "users": 500, "orders": 1000}`, each a dict keyed by id |
| `tasks.json` | 114 tasks: user scenario + expected actions + checks |
| `split_tasks.json` | `train` 74, `test` 40, `base` 114 (task ids) |
| `policy.md` | the agent's policy (the τ³ version is stricter than the old `wiki.md`) |

## Data shapes

- **User** `user_id`, `name{first_name,last_name}`, `address{address1,address2,city,country,state,zip}`, `email`, `payment_methods{id: {source, id, ...}}`, `orders[order_id]`. Payment `source` is `credit_card` (`brand`, `last_four`), `paypal`, or `gift_card` (`balance`).
- **Product** `product_id`, `name`, `variants{item_id: {item_id, options{}, available, price}}`. Product ids and item ids are different number spaces.
- **Order** `order_id` (`#W…`), `user_id`, `address`, `items[{name, product_id, item_id, price, options}]`, `fulfillments[{tracking_id[], item_ids[]}]`, `status`, `payment_history[{transaction_type: payment|refund, amount, payment_method_id}]`, plus optional `cancel_reason`, `exchange_*`, `return_*` fields that tools fill in.
- **Order status**: `pending`, `processed`, `delivered`, `cancelled` in the data. Tools add `pending (item modified)`, `exchange requested` and `return requested`.

## How a task is scored

1. The gold actions are replayed on a fresh copy of the DB. The agent's final DB is then compared with that gold DB **by hash of the whole DB**. Any extra or different write fails the task.
2. 112 of 114 tasks also have `NL_ASSERTION` in `reward_basis`: an LLM judge checks statements about the conversation (40 tasks have assertions). 36 tasks also list `communicate_info`, which are values the agent must tell the user.
3. A simulated user (an LLM) plays the customer from `user_scenario` (`reason_for_call`, `known_info`, `unknown_info`, `task_instructions`).

**Consequence for our design:** our tools must change the data *exactly* as the τ³ tools do, including field names, sort order, rounding and the extra fields they add. Then we can export our DB back to the `db.json` shape and compare hashes. So the SQLite store must round-trip to identical JSON.

## Tools (16) and how often the 114 tasks use them

| Tool | Kind | Uses | Rule enforced in the tool |
|---|---|---|---|
| get_order_details | read | 168 | – |
| find_user_id_by_name_zip | read | 61 | accent- and case-folded name match. Zip matches exactly. More than one match is an error |
| get_user_details | read | 57 | – |
| get_product_details | read | 54 | – |
| return_delivered_order_items | write | 41 | status must be `delivered`. Refund goes to the original payment method or any gift card. Item counts must exist |
| modify_pending_order_items | write | 39 | status must be exactly `pending`. Same product, available variant, new ≠ old. Gift card must cover the difference. Status becomes `pending (item modified)` |
| exchange_delivered_order_items | write | 35 | status must be `delivered`. Same product, available variant. Gift card must cover the difference. Stores `exchange_*` fields |
| cancel_pending_order | write | 25 | status must be exactly `pending`. Reason must be `no longer needed` or `ordered by mistake`. A refund row is added for each payment, and gift cards are refunded right away |
| modify_pending_order_address | write | 24 | status contains `pending` |
| find_user_id_by_email | read | 14 | folded, unique match |
| calculate | generic | 13 | only digits and `+-*/(). ` are allowed. Result rounded to 2 decimals |
| modify_user_address | write | 11 | – |
| transfer_to_human_agents | generic | 4 | returns "Transfer successful" and ends the conversation |
| get_item_details | read | 3 | – |
| modify_pending_order_payment | write | 1 | status contains `pending`. Exactly one payment. New method must differ. Gift card must cover the amount. Adds payment + refund rows and updates gift card balances |
| list_all_product_types | read | – | returns a JSON string `{name: product_id}`, sorted |

Errors are raised as `ValueError("…")`, and the message is shown to the agent.

## Quirks we must copy to get matching hashes

- `modify_pending_order_items`: the price and options written to **every** changed item come from the *last* variant checked (a loop-variable bug in the original). This only matters when several items change.
- `modify_pending_order_items` always adds a payment-history row (`payment` if diff > 0, otherwise `refund` with `abs(diff)`), even when the difference is 0. The diff is **not** rounded before it's stored, but gift card balances are rounded.
- `exchange_*` and `return_items` lists are stored **sorted**.
- The order-address and payment tools accept any status that *contains* `pending`, but cancel and modify-items need exactly `pending`.

## Policy checks we add in code (step 2.5, `tools/policy.py`)

The τ³ tools do **not** check *who* is asking. `ShopSession` (one per conversation) adds these checks:

- Every account tool needs an authenticated user. Only `calculate` and `transfer_to_human_agents` work before login.
- One user per conversation: logging in as a second user is refused.
- `user_id` and `order_id` arguments must belong to the logged-in user. Another user's order shows as "Order not found", so we don't reveal that it exists.

These checks never block an expected action: a test replays all 114 tasks through `ShopSession`. Some expected lookups fail on purpose, when the simulated customer gives a wrong email or zip.

## Policy rules the prompt alone covers in τ³ (we will also enforce some in code)

- Authenticate first (email, or name + zip), even if the user gives a user id.
- One user per conversation.
- List the action details and get an explicit "yes" before any write.
- One tool call at a time, and no text alongside a tool call.
- Transfer to a human only when the request is out of scope. Then send "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
