from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.config import load_config  # noqa: E402
from shipvoice.providers import build_retriever  # noqa: E402


async def main() -> None:
    config = load_config()
    retriever = build_retriever(config)
    test_path = ROOT / "data" / "tests" / "eval_questions.csv"
    rows: list[dict[str, str]] = []
    with test_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    checked = 0
    hit_at_1 = 0
    hit_at_3 = 0
    for row in rows:
        expected = row.get("expected_title", "").strip()
        if not expected:
            continue
        checked += 1
        hits = await retriever.retrieve(row["question"], top_k=3)
        titles = [hit.title for hit in hits]
        if titles and titles[0] == expected:
            hit_at_1 += 1
        if expected in titles:
            hit_at_3 += 1
        print(f"{row['id']} expected={expected} top={titles}")

    print(f"\nchecked={checked} hit@1={hit_at_1}/{checked} hit@3={hit_at_3}/{checked}")
    if checked and hit_at_3 < checked:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())

