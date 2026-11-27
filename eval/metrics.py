"""Evaluation metrics: pass^k (tau-bench), plus average turns and tool calls."""
from collections import defaultdict
from math import comb


def pass_hat_k(results: list[dict], k: int) -> float:
    """Chance that k random trials of a task ALL succeed, averaged over tasks.
    Per task: C(successes, k) / C(trials, k). pass^1 is the plain success rate."""
    by_task = defaultdict(list)
    for r in results:
        by_task[r["task_id"]].append(r["reward"] == 1.0)
    scores = [comb(sum(runs), k) / comb(len(runs), k) for runs in by_task.values() if len(runs) >= k]
    if not scores:
        raise ValueError(f"no task has {k} trials")
    return sum(scores) / len(scores)


def summary(results: list[dict]) -> dict:
    """pass^1..pass^n (n = fewest trials of any task), average turns/tool calls, per-task successes."""
    by_task = defaultdict(list)
    for r in results:
        by_task[r["task_id"]].append(r["reward"] == 1.0)
    n = min(len(runs) for runs in by_task.values())
    return {
        "tasks": len(by_task),
        "trials": n,
        "pass_hat_k": {k: pass_hat_k(results, k) for k in range(1, n + 1)},
        "avg_user_turns": sum(r["user_turns"] for r in results) / len(results),
        "avg_tool_calls": sum(r["tool_calls"] for r in results) / len(results),
        "per_task": {t: f"{sum(runs)}/{len(runs)}" for t, runs in by_task.items()},
    }
