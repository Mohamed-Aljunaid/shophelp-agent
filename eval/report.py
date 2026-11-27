"""Save eval results to eval/reports/<name>/:
  results.jsonl   one line per (task, trial), written as each run finishes (lets a run resume)
  summary.json    pass^k and averages
  failures/       one Markdown transcript per failed run, with expected vs actual writes
"""
import json
from pathlib import Path

from eval.metrics import summary

REPORTS = Path(__file__).resolve().parent / "reports"
READ_ONLY = ("get_", "find_", "list_", "calculate")


def load_results(out_dir: Path) -> list[dict]:
    path = out_dir / "results.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_result(out_dir: Path, result: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "results.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(result) + "\n")


def _writes(actions: list[dict]) -> list[str]:
    return [f"{a['name']}({json.dumps(a['args'])})" for a in actions if not a["name"].startswith(READ_ONLY)]


def failure_markdown(result: dict, task: dict) -> str:
    """A readable transcript of one failed run, with the gold writes for comparison."""
    expected = _writes([{"name": a["name"], "args": a["arguments"]} for a in task["evaluation_criteria"]["actions"] or []])
    calls, results_by_id = [], {m["tool_call_id"]: m["content"] for m in result["messages"] if m["role"] == "tool"}
    lines = []
    for m in result["messages"]:
        if m["role"] == "user":
            lines.append(f"**customer:** {m['content']}\n")
        elif m["role"] == "assistant":
            for c in m.get("tool_calls") or []:
                calls.append({"name": c["name"], "args": c["args"]})
                out = results_by_id.get(c["id"], "")
                lines.append(f"- `{c['name']}({json.dumps(c['args'])})` → `{out[:200]}`")
            if m.get("content"):
                lines.append(f"\n**agent:** {m['content']}\n")
    reason = task["user_scenario"]["instructions"]
    reason = reason.get("reason_for_call", "") if isinstance(reason, dict) else reason
    return "\n".join([
        f"# Task {result['task_id']}, trial {result['trial']}: failed",
        f"\nend: `{result['end']}` · customer turns: {result['user_turns']} · tool calls: {result['tool_calls']}",
        f"\n**Scenario:** {reason}",
        "\n**Expected writes:**", *[f"- `{w}`" for w in expected or ["(none)"]],
        "\n**Agent writes:**", *[f"- `{w}`" for w in _writes(calls) or ["(none)"]],
        "\n## Conversation\n", *lines,
    ]) + "\n"


def write_report(out_dir: Path, results: list[dict], tasks: dict[str, dict]) -> dict:
    """Write summary.json and failures/*.md; return the summary."""
    s = summary(results)
    (out_dir / "summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    failures = out_dir / "failures"
    failures.mkdir(exist_ok=True)
    for old in failures.glob("*.md"):
        old.unlink()
    for r in results:
        if r["reward"] != 1.0:
            name = f"task{int(r['task_id']):03d}_trial{r['trial']}.md"
            (failures / name).write_text(failure_markdown(r, tasks[r["task_id"]]), encoding="utf-8")
    return s
