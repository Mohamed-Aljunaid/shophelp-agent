"""pass^k against hand-computed values."""
import pytest

from eval.metrics import pass_hat_k, summary


def runs(task, *rewards):
    return [{"task_id": task, "reward": r, "user_turns": 4, "tool_calls": 2} for r in rewards]


def test_pass_hat_k():
    results = runs("a", 1, 1, 1) + runs("b", 1, 1, 0) + runs("c", 0, 0, 0)
    assert pass_hat_k(results, 1) == pytest.approx((1 + 2 / 3 + 0) / 3)
    assert pass_hat_k(results, 2) == pytest.approx((1 + 1 / 3 + 0) / 3)  # C(2,2)/C(3,2) = 1/3
    assert pass_hat_k(results, 3) == pytest.approx(1 / 3)
    with pytest.raises(ValueError):
        pass_hat_k(results, 4)


def test_summary():
    s = summary(runs("a", 1, 0) + runs("b", 1, 1))
    assert s["tasks"] == 2 and s["trials"] == 2
    assert s["pass_hat_k"] == {1: 0.75, 2: 0.5}
    assert s["avg_user_turns"] == 4 and s["per_task"] == {"a": "1/2", "b": "2/2"}
