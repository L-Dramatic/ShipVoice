from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402


async def main() -> None:
    pipeline = VoiceQAPipeline()
    test_path = ROOT / "data" / "tests" / "eval_questions.csv"
    result_path = ROOT / "results" / "latency_metrics.csv"
    result_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    with test_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for item in reader:
            for mode in ["baseline", "streaming", "full"]:
                result = await pipeline.run_once(
                    item["question"],
                    question_id=item["id"],
                    category=item["category"],
                    mode=mode,
                )
                row = result.metrics.to_row()
                row["question"] = item["question"]
                row["expected_behavior"] = item["expected_behavior"]
                rows.append(row)
                print(
                    f"{item['id']} {mode:<9} first_audio={result.metrics.first_audio_ms:>4}ms "
                    f"total={result.metrics.total_ms:>4}ms gate={result.metrics.gate_label}"
                )

    fieldnames = list(rows[0].keys()) if rows else []
    with result_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {result_path}")


if __name__ == "__main__":
    asyncio.run(main())

