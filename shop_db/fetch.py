"""Download the tau3-bench retail domain files (MIT, Sierra) into data/tau2-retail/.

Run: uv run python -m shop_db.fetch
"""
import urllib.request
from pathlib import Path

# Pinned so the data and tasks never change under us.
COMMIT = "768f3d8fe8528b4f32a5096f9ed008ae50f48ead"
BASE = f"https://raw.githubusercontent.com/sierra-research/tau2-bench/{COMMIT}/data/tau2/domains/retail/"
FILES = ["db.json", "tasks.json", "split_tasks.json", "policy.md"]
DEST = Path(__file__).resolve().parent.parent / "data" / "tau2-retail"


def fetch(dest: Path = DEST) -> None:
    """Download each retail file into dest, skipping files already there."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = dest / name
        if target.exists():
            continue
        with urllib.request.urlopen(BASE + name, timeout=60) as resp:
            target.write_bytes(resp.read())
        print(f"downloaded {name}")


if __name__ == "__main__":
    fetch()
