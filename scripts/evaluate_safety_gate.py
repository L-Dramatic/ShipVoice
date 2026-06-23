from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402


EXPECTED_BLOCK_LABELS = {"unsafe", "off_domain"}


def expected_allowed(label: str) -> bool:
    return label not in EXPECTED_BLOCK_LABELS


def read_cases(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


async def run_case(
    pipeline: VoiceQAPipeline,
    case: dict[str, str],
    *,
    mode: str,
    gate_only: bool,
) -> dict[str, Any]:
    question = case["question"]
    if gate_only:
        transcript, term_hits = pipeline.corrector.correct(question)
        gate = pipeline.gate.classify(transcript)
        metrics = {
            "first_audio_ms": 0,
            "server_audio_payload_ready_ms": 0,
            "total_ms": 0,
            "asr_ms": 0,
            "retrieval_ms": 0,
            "evidence_count": 0,
        }
        answer = ""
    else:
        result = await pipeline.run_once(
            question,
            question_id=case["id"],
            category=case["category"],
            mode=mode,
        )
        transcript = result.transcript
        term_hits = []
        gate = result.gate
        metrics = result.metrics.to_row()
        answer = result.answer

    expected_gate = case["expected_gate"]
    predicted_allowed = bool(gate.allowed)
    should_allow = expected_allowed(expected_gate)
    label_match = gate.label == expected_gate
    decision_match = predicted_allowed == should_allow

    return {
        "id": case["id"],
        "category": case["category"],
        "risk_type": case["risk_type"],
        "question": question,
        "transcript": transcript,
        "expected_gate": expected_gate,
        "predicted_gate": gate.label,
        "expected_allowed": should_allow,
        "predicted_allowed": predicted_allowed,
        "label_match": label_match,
        "decision_match": decision_match,
        "reason": gate.reason,
        "term_hits": ";".join(term_hits),
        "first_audio_ms": metrics["first_audio_ms"],
        "server_audio_payload_ready_ms": metrics.get("server_audio_payload_ready_ms", metrics["first_audio_ms"]),
        "total_ms": metrics["total_ms"],
        "asr_ms": metrics["asr_ms"],
        "retrieval_ms": metrics["retrieval_ms"],
        "evidence_count": metrics["evidence_count"],
        "answer_preview": answer[:160].replace("\n", " "),
        "expected_behavior": case["expected_behavior"],
    }


def summarize(rows: list[dict[str, Any]], *, mode: str, gate_only: bool) -> dict[str, Any]:
    total = len(rows)
    label_matches = sum(1 for row in rows if row["label_match"])
    decision_matches = sum(1 for row in rows if row["decision_match"])
    expected_blocked = [row for row in rows if not row["expected_allowed"]]
    expected_allowed_rows = [row for row in rows if row["expected_allowed"]]
    false_allow = [row for row in rows if not row["expected_allowed"] and row["predicted_allowed"]]
    false_block = [row for row in rows if row["expected_allowed"] and not row["predicted_allowed"]]

    confusion: dict[str, dict[str, int]] = {}
    by_category: dict[str, dict[str, int]] = {}
    for row in rows:
        expected = str(row["expected_gate"])
        predicted = str(row["predicted_gate"])
        confusion.setdefault(expected, {})
        confusion[expected][predicted] = confusion[expected].get(predicted, 0) + 1

        category = str(row["category"])
        stats = by_category.setdefault(category, {"total": 0, "label_match": 0, "decision_match": 0})
        stats["total"] += 1
        stats["label_match"] += int(bool(row["label_match"]))
        stats["decision_match"] += int(bool(row["decision_match"]))

    latency_rows = [row for row in rows if int(row["total_ms"]) > 0]
    avg_first_audio = (
        sum(int(row.get("server_audio_payload_ready_ms", row["first_audio_ms"])) for row in latency_rows) / len(latency_rows)
        if latency_rows
        else 0.0
    )
    avg_total = sum(int(row["total_ms"]) for row in latency_rows) / len(latency_rows) if latency_rows else 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "gate_only": gate_only,
        "total": total,
        "label_matches": label_matches,
        "decision_matches": decision_matches,
        "label_accuracy": pct(label_matches, total),
        "decision_accuracy": pct(decision_matches, total),
        "expected_block_count": len(expected_blocked),
        "expected_allow_count": len(expected_allowed_rows),
        "false_allow_count": len(false_allow),
        "false_block_count": len(false_block),
        "block_recall": pct(len(expected_blocked) - len(false_allow), len(expected_blocked)),
        "allow_recall": pct(len(expected_allowed_rows) - len(false_block), len(expected_allowed_rows)),
        "avg_first_audio_ms": avg_first_audio,
        "avg_server_audio_payload_ready_ms": avg_first_audio,
        "avg_total_ms": avg_total,
        "confusion": confusion,
        "by_category": by_category,
        "critical_failures": [
            {
                "id": row["id"],
                "expected_gate": row["expected_gate"],
                "predicted_gate": row["predicted_gate"],
                "question": row["question"],
            }
            for row in false_allow
        ],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "# ShipVoice Safety Gate Evaluation",
        "",
        f"- Mode: `{summary['mode']}`",
        f"- Gate only: `{summary['gate_only']}`",
        f"- Total cases: {summary['total']}",
        f"- Exact label accuracy: {summary['label_accuracy']:.1%} ({summary['label_matches']}/{summary['total']})",
        f"- Allow/block decision accuracy: {summary['decision_accuracy']:.1%} ({summary['decision_matches']}/{summary['total']})",
        f"- Block recall: {summary['block_recall']:.1%}",
        f"- Allow recall: {summary['allow_recall']:.1%}",
        f"- False allow count: {summary['false_allow_count']}",
        f"- False block count: {summary['false_block_count']}",
        "",
        "## Case Results",
        "",
        "| ID | Category | Risk | Expected | Predicted | Decision |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        decision = "PASS" if row["label_match"] and row["decision_match"] else "FAIL"
        lines.append(
            f"| {row['id']} | {row['category']} | {row['risk_type']} | "
            f"{row['expected_gate']} | {row['predicted_gate']} | {decision} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


async def main_async(args: argparse.Namespace) -> int:
    pipeline = VoiceQAPipeline()
    cases = read_cases(args.input)
    rows: list[dict[str, Any]] = []
    for case in cases:
        row = await run_case(pipeline, case, mode=args.mode, gate_only=args.gate_only)
        rows.append(row)
        status = "PASS" if row["label_match"] and row["decision_match"] else "FAIL"
        print(
            f"{row['id']} {status:<4} expected={row['expected_gate']:<11} "
            f"predicted={row['predicted_gate']:<11} allowed={row['predicted_allowed']}"
        )

    summary = summarize(rows, mode=args.mode, gate_only=args.gate_only)
    write_csv(args.output_csv, rows)
    args.output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(args.output_report, rows, summary)

    print(f"\nSafety label accuracy: {summary['label_accuracy']:.1%}")
    print(f"Decision accuracy: {summary['decision_accuracy']:.1%}")
    print(f"False allow count: {summary['false_allow_count']}")
    print(f"Wrote {args.output_csv}")
    print(f"Wrote {args.output_json}")
    print(f"Wrote {args.output_report}")

    if args.fail_on_critical and summary["false_allow_count"]:
        return 2
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate ShipVoice safety/domain gate behavior.")
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "tests" / "safety_eval.csv")
    parser.add_argument("--output-csv", type=Path, default=ROOT / "results" / "safety_gate_eval.csv")
    parser.add_argument("--output-json", type=Path, default=ROOT / "results" / "safety_gate_eval_summary.json")
    parser.add_argument("--output-report", type=Path, default=ROOT / "results" / "safety_gate_eval_report.md")
    parser.add_argument("--mode", default="full", choices=["baseline", "streaming", "rag", "guarded", "full"])
    parser.add_argument(
        "--gate-only",
        action="store_true",
        help="Evaluate the gate directly without invoking the full ASR/LLM/TTS chain.",
    )
    parser.add_argument("--fail-on-critical", action="store_true")
    return parser.parse_args()


def main() -> None:
    raise SystemExit(asyncio.run(main_async(parse_args())))


if __name__ == "__main__":
    main()
