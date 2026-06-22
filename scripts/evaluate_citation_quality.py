from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.models import RetrievalHit  # noqa: E402
from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402


BLOCKED_CATEGORIES = {"off_domain", "unsafe", "prompt_injection"}
REQUIRED_CITATION_FIELDS = ("record_id", "title", "source", "risk_level", "confidence")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_expected_ids(corpus_path: Path) -> dict[str, str]:
    if not corpus_path.exists():
        return {}
    mapping: dict[str, str] = {}
    for line in corpus_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        title = str(item.get("title", "")).strip()
        record_id = str(item.get("id", "")).strip()
        if title and record_id:
            mapping[title] = record_id
    return mapping


def ratio(numerator: float, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def citation_complete(hit: RetrievalHit) -> bool:
    for field in REQUIRED_CITATION_FIELDS:
        value = getattr(hit, field)
        if field == "confidence":
            if not isinstance(value, int | float) or value <= 0:
                return False
            continue
        if not str(value).strip():
            return False
    return bool(hit.matched_terms)


def answer_contains_citation(answer: str, expected_record_id: str, top_record_id: str) -> bool:
    candidates = [value for value in [expected_record_id, top_record_id] if value]
    return any(f"[{value}]" in answer or value in answer for value in candidates)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    title_rows = [row for row in rows if row["expected_title"]]
    id_rows = [row for row in title_rows if row["expected_record_id"]]
    blocked_rows = [row for row in rows if not row["expected_allowed"]]
    citations = sum(int(row["citation_count"]) for row in rows)
    complete_citations = sum(int(row["complete_citation_count"]) for row in rows)
    confidence_values = [float(row["top1_confidence"]) for row in rows if row["top1_confidence"] != ""]
    latency_values = [int(row["total_ms"]) for row in rows if row["total_ms"] != ""]

    return {
        "total": len(rows),
        "allowed_cases": len(title_rows),
        "blocked_cases": len(blocked_rows),
        "gate_allowed_accuracy": ratio(sum(1 for row in rows if row["gate_allowed_match"]), len(rows)),
        "blocked_no_citation_rate": ratio(
            sum(1 for row in blocked_rows if int(row["citation_count"]) == 0),
            len(blocked_rows),
        ),
        "citation_title_hit_at_1": ratio(sum(1 for row in title_rows if row["title_hit_at_1"]), len(title_rows)),
        "citation_title_hit_at_3": ratio(sum(1 for row in title_rows if row["title_hit_at_3"]), len(title_rows)),
        "citation_id_hit_at_1": ratio(sum(1 for row in id_rows if row["id_hit_at_1"]), len(id_rows)),
        "citation_id_hit_at_3": ratio(sum(1 for row in id_rows if row["id_hit_at_3"]), len(id_rows)),
        "top1_schema_completeness": ratio(sum(1 for row in title_rows if row["top1_complete"]), len(title_rows)),
        "citation_schema_completeness": ratio(complete_citations, citations),
        "answer_citation_id_rate": ratio(sum(1 for row in title_rows if row["answer_has_citation_id"]), len(title_rows)),
        "avg_top1_confidence": mean(confidence_values) if confidence_values else 0.0,
        "avg_total_ms": mean(latency_values) if latency_values else 0.0,
        "total_citations": citations,
        "complete_citations": complete_citations,
        "mode": rows[0]["mode"] if rows else "",
    }


def render_markdown(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# ShipVoice Citation Quality Evaluation",
        "",
        "This report evaluates whether generated answers are grounded in auditable RAG citations, not just whether retrieval returns any text.",
        "",
        f"- Samples: {summary['total']}",
        f"- Allowed citation cases: {summary['allowed_cases']}",
        f"- Blocked cases: {summary['blocked_cases']}",
        f"- Gate allowed accuracy: {summary['gate_allowed_accuracy']:.2%}",
        f"- Citation title hit@1: {summary['citation_title_hit_at_1']:.2%}",
        f"- Citation title hit@3: {summary['citation_title_hit_at_3']:.2%}",
        f"- Citation ID hit@1: {summary['citation_id_hit_at_1']:.2%}",
        f"- Citation ID hit@3: {summary['citation_id_hit_at_3']:.2%}",
        f"- Top-1 schema completeness: {summary['top1_schema_completeness']:.2%}",
        f"- Citation schema completeness: {summary['citation_schema_completeness']:.2%}",
        f"- Answer citation ID rate: {summary['answer_citation_id_rate']:.2%}",
        f"- Avg top-1 confidence: {summary['avg_top1_confidence']:.3f}",
        f"- Avg total latency: {summary['avg_total_ms']:.0f} ms",
        "",
        "| ID | Category | Gate | Expected citation | Top-1 citation | Hit@3 | Complete | Answer cites ID |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        expected = row["expected_record_id"] or row["expected_title"] or "blocked"
        top = row["top1_record_id"] or row["top1_title"] or "none"
        hit_at_3 = "Yes" if row["title_hit_at_3"] else ("n/a" if not row["expected_title"] else "No")
        complete = "Yes" if row["top1_complete"] else ("n/a" if not row["expected_title"] else "No")
        answer_cites = "Yes" if row["answer_has_citation_id"] else ("n/a" if not row["expected_title"] else "No")
        lines.append(
            f"| {row['id']} | {row['category']} | {row['gate_label']} | {expected} | {top} | "
            f"{hit_at_3} | {complete} | {answer_cites} |"
        )
    lines.append("")
    return "\n".join(lines)


async def evaluate(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    test_rows = read_csv(args.input)
    title_to_id = load_expected_ids(args.corpus)
    pipeline = VoiceQAPipeline()
    rows: list[dict[str, Any]] = []

    for item in test_rows:
        question = item["question"].strip()
        category = item.get("category", "").strip()
        expected_title = item.get("expected_title", "").strip()
        expected_record_id = title_to_id.get(expected_title, "")
        expected_allowed = category not in BLOCKED_CATEGORIES

        result = await pipeline.run_once(
            question,
            question_id=item["id"],
            category=category,
            mode=args.mode,
        )
        citations = result.evidence
        titles = [hit.title for hit in citations]
        ids = [hit.record_id for hit in citations]
        top_hit = citations[0] if citations else None
        complete_flags = [citation_complete(hit) for hit in citations]

        rows.append(
            {
                "id": item["id"],
                "category": category,
                "question": question,
                "mode": args.mode,
                "expected_allowed": expected_allowed,
                "gate_allowed": result.gate.allowed,
                "gate_allowed_match": result.gate.allowed == expected_allowed,
                "gate_label": result.gate.label,
                "expected_title": expected_title,
                "expected_record_id": expected_record_id,
                "citation_count": len(citations),
                "complete_citation_count": sum(1 for flag in complete_flags if flag),
                "top1_title": top_hit.title if top_hit else "",
                "top1_record_id": top_hit.record_id if top_hit else "",
                "top1_source": top_hit.source if top_hit else "",
                "top1_risk_level": top_hit.risk_level if top_hit else "",
                "top1_confidence": top_hit.confidence if top_hit else "",
                "top1_matched_terms": " | ".join(top_hit.matched_terms) if top_hit else "",
                "top1_complete": bool(top_hit and citation_complete(top_hit)),
                "title_hit_at_1": bool(expected_title and titles and titles[0] == expected_title),
                "title_hit_at_3": bool(expected_title and expected_title in titles[:3]),
                "id_hit_at_1": bool(expected_record_id and ids and ids[0] == expected_record_id),
                "id_hit_at_3": bool(expected_record_id and expected_record_id in ids[:3]),
                "answer_has_citation_id": bool(
                    expected_title
                    and answer_contains_citation(result.answer, expected_record_id, top_hit.record_id if top_hit else "")
                ),
                "total_ms": result.metrics.total_ms,
                "answer_preview": result.answer[:180].replace("\n", " "),
            }
        )

    return summarize(rows), rows


async def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ShipVoice RAG citation quality.")
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "tests" / "eval_questions.csv")
    parser.add_argument("--corpus", type=Path, default=ROOT / "data" / "knowledge" / "ship_safety_corpus.jsonl")
    parser.add_argument("--output-csv", type=Path, default=ROOT / "results" / "citation_quality_eval.csv")
    parser.add_argument("--output-json", type=Path, default=ROOT / "results" / "citation_quality_summary.json")
    parser.add_argument("--output-report", type=Path, default=ROOT / "results" / "citation_quality_report.md")
    parser.add_argument("--mode", default="full")
    parser.add_argument("--fail-on-threshold", action="store_true")
    args = parser.parse_args()

    summary, rows = await evaluate(args)

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)

    args.output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_report.write_text(render_markdown(summary, rows), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.fail_on_threshold:
        failed = (
            summary["gate_allowed_accuracy"] < 1.0
            or summary["citation_title_hit_at_3"] < 1.0
            or summary["citation_id_hit_at_3"] < 1.0
            or summary["top1_schema_completeness"] < 1.0
            or summary["answer_citation_id_rate"] < 1.0
        )
        if failed:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
