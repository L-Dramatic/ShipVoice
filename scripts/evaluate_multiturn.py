from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def ratio(numerator: float, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


async def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ShipVoice multi-turn context handling.")
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "tests" / "multiturn_eval.jsonl")
    parser.add_argument("--output-csv", type=Path, default=ROOT / "results" / "multiturn_eval.csv")
    parser.add_argument("--output-json", type=Path, default=ROOT / "results" / "multiturn_eval_summary.json")
    parser.add_argument("--output-report", type=Path, default=ROOT / "results" / "multiturn_eval_report.md")
    parser.add_argument("--mode", default="full")
    parser.add_argument("--fail-on-threshold", action="store_true")
    args = parser.parse_args()

    dialogs = read_jsonl(args.input)
    pipeline = VoiceQAPipeline()
    rows: list[dict[str, object]] = []

    for dialog in dialogs:
        history: list[dict[str, str]] = []
        dialog_id = str(dialog["dialog_id"])
        scenario = str(dialog.get("scenario", dialog_id))
        for turn_index, turn in enumerate(dialog["turns"], start=1):
            question = str(turn["question"])
            result = await pipeline.run_once(
                question,
                history=history,
                question_id=str(turn["turn_id"]),
                category=scenario,
                mode=args.mode,
            )
            expected_gate = str(turn["expected_gate"])
            expected_title = str(turn.get("expected_title", "")).strip()
            expected_keywords = [str(x) for x in turn.get("expected_keywords", [])]
            evidence_titles = [hit.title for hit in result.evidence]
            top1_title = evidence_titles[0] if evidence_titles else ""
            gate_match = result.gate.label == expected_gate
            top1_match = bool(expected_title) and top1_title == expected_title
            title_hit = bool(expected_title) and expected_title in evidence_titles
            keyword_hits = [kw for kw in expected_keywords if kw and kw in result.answer]
            keyword_recall = ratio(len(keyword_hits), len(expected_keywords)) if expected_keywords else 1.0
            requires_context = bool(turn.get("requires_context", False))
            history_turns = len(history)
            followup_grounded = requires_context and history_turns > 0 and title_hit

            rows.append(
                {
                    "dialog_id": dialog_id,
                    "scenario": scenario,
                    "turn_id": str(turn["turn_id"]),
                    "turn_index": turn_index,
                    "requires_context": requires_context,
                    "history_turns": history_turns,
                    "question": question,
                    "expected_gate": expected_gate,
                    "predicted_gate": result.gate.label,
                    "gate_match": gate_match,
                    "expected_title": expected_title,
                    "top1_title": top1_title,
                    "top1_match": top1_match,
                    "title_hit": title_hit,
                    "expected_keywords": " | ".join(expected_keywords),
                    "keyword_hits": " | ".join(keyword_hits),
                    "keyword_recall": f"{keyword_recall:.4f}",
                    "followup_grounded": followup_grounded,
                    "total_ms": result.metrics.total_ms,
                    "first_audio_ms": result.metrics.first_audio_ms,
                    "server_audio_payload_ready_ms": result.metrics.server_audio_payload_ready_ms,
                    "answer": result.answer,
                }
            )

            history.append({"role": "user", "content": question})
            history.append({"role": "assistant", "content": result.answer})

    turn_count = len(rows)
    followup_rows = [row for row in rows if bool(row["requires_context"])]
    title_rows = [row for row in rows if str(row["expected_title"]).strip()]
    summary = {
        "dialogs": len(dialogs),
        "turns": turn_count,
        "followup_turns": len(followup_rows),
        "gate_accuracy": ratio(sum(1 for row in rows if bool(row["gate_match"])), turn_count),
        "top1_title_accuracy": ratio(sum(1 for row in title_rows if bool(row["top1_match"])), len(title_rows)),
        "title_hit_at_3": ratio(sum(1 for row in title_rows if bool(row["title_hit"])), len(title_rows)),
        "keyword_recall": ratio(sum(float(str(row["keyword_recall"])) for row in rows), turn_count),
        "followup_grounding_accuracy": ratio(sum(1 for row in followup_rows if bool(row["followup_grounded"])), len(followup_rows)),
        "avg_total_ms": ratio(sum(int(row["total_ms"]) for row in rows), turn_count),
        "avg_first_audio_ms": ratio(sum(int(row["first_audio_ms"]) for row in rows), turn_count),
        "avg_server_audio_payload_ready_ms": ratio(
            sum(int(row.get("server_audio_payload_ready_ms", row["first_audio_ms"])) for row in rows),
            turn_count,
        ),
        "mode": args.mode,
    }

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)

    args.output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report_lines = [
        "# ShipVoice Multi-turn Evaluation",
        "",
        f"- Dialogs: {summary['dialogs']}",
        f"- Turns: {summary['turns']}",
        f"- Follow-up turns: {summary['followup_turns']}",
        f"- Gate accuracy: {summary['gate_accuracy']:.2%}",
        f"- Top-1 title accuracy: {summary['top1_title_accuracy']:.2%}",
        f"- Title hit@3: {summary['title_hit_at_3']:.2%}",
        f"- Keyword recall: {summary['keyword_recall']:.2%}",
        f"- Follow-up grounding accuracy: {summary['followup_grounding_accuracy']:.2%}",
        f"- Avg total latency: {summary['avg_total_ms']:.0f} ms",
        f"- Avg audio payload ready latency: {summary['avg_server_audio_payload_ready_ms']:.0f} ms",
        "",
        "| Turn | Context | Gate | Title hit | Keyword recall |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        report_lines.append(
            f"| {row['turn_id']} | {row['history_turns']} | {row['predicted_gate']} | "
            f"{'Yes' if row['title_hit'] else 'No'} | {float(str(row['keyword_recall'])):.0%} |"
        )
    args.output_report.write_text("\n".join(report_lines), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.fail_on_threshold:
        if summary["gate_accuracy"] < 1.0 or summary["followup_grounding_accuracy"] < 0.8:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
