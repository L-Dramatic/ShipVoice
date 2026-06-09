from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run one ShipVoice pipeline question.")
    parser.add_argument("question")
    parser.add_argument("--mode", default="full", choices=["baseline", "streaming", "rag", "guarded", "full"])
    parser.add_argument("--json", action="store_true", help="Print full JSON result.")
    args = parser.parse_args()

    pipeline = VoiceQAPipeline()
    result = await pipeline.run_once(args.question, mode=args.mode)
    if args.json:
        print(
            json.dumps(
                {
                    "question": result.question,
                    "transcript": result.transcript,
                    "answer": result.answer,
                    "gate": result.gate.__dict__,
                    "evidence": [hit.__dict__ for hit in result.evidence],
                    "events": [event.to_dict() for event in result.events],
                    "metrics": result.metrics.to_row(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    print(f"问题：{result.question}")
    print(f"转写：{result.transcript}")
    print(f"门控：{result.gate.label} / {result.gate.reason}")
    print("证据：")
    for idx, hit in enumerate(result.evidence, start=1):
        print(f"  {idx}. {hit.title} score={hit.score}")
    print(f"回答：{result.answer}")
    print(f"指标：first_audio={result.metrics.first_audio_ms}ms total={result.metrics.total_ms}ms")


if __name__ == "__main__":
    asyncio.run(main())

