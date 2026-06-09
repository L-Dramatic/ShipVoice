from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.config import load_config  # noqa: E402


PUNCT_RE = re.compile(r"[\s，。！？；：、“”‘’（）()\[\]{}《》<>.,!?;:'\"`~@#$%^&*_+=|\\/，、-]+")


def normalize_text(text: str) -> str:
    return PUNCT_RE.sub("", text.strip().lower())


def tokenize_for_wer(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    ascii_words = re.findall(r"[a-z0-9]+", normalized)
    chinese_chars = [ch for ch in normalized if "\u4e00" <= ch <= "\u9fff"]
    others = [ch for ch in normalized if not ("\u4e00" <= ch <= "\u9fff") and not ch.isascii()]
    return ascii_words + chinese_chars + others


def edit_distance(left: list[str], right: list[str]) -> int:
    if not left:
        return len(right)
    if not right:
        return len(left)
    prev = list(range(len(right) + 1))
    for i, l_item in enumerate(left, start=1):
        curr = [i]
        for j, r_item in enumerate(right, start=1):
            cost = 0 if l_item == r_item else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def ratio(distance: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return distance / denominator


def term_hits(reference: str, hypothesis: str, domain_terms: list[str]) -> tuple[int, int, list[str], list[str]]:
    expected = [term for term in domain_terms if term and term in reference]
    hit = [term for term in expected if term in hypothesis]
    missed = [term for term in expected if term not in hypothesis]
    return len(hit), len(expected), hit, missed


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def evaluate_row(row: dict[str, str], domain_terms: list[str], hypothesis_column: str) -> dict[str, Any]:
    audio_path = ROOT / row["audio_path"]
    reference = row["transcript"].strip()
    hypothesis = row.get(hypothesis_column, "").strip()
    status = row.get("status", "").strip().lower()
    audio_exists = audio_path.exists()

    if not hypothesis:
        eval_status = "missing_asr" if status in {"recorded", "transcribed"} or audio_exists else "missing_audio"
        return {
            **row,
            "audio_exists": audio_exists,
            "eval_status": eval_status,
            "cer": "",
            "wer": "",
            "char_edits": "",
            "word_edits": "",
            "ref_chars": len(normalize_text(reference)),
            "ref_tokens": len(tokenize_for_wer(reference)),
            "term_hit_count": "",
            "term_expected_count": "",
            "term_recall": "",
            "term_hits": "",
            "term_missed": "",
        }

    ref_chars = list(normalize_text(reference))
    hyp_chars = list(normalize_text(hypothesis))
    char_edits = edit_distance(ref_chars, hyp_chars)
    cer = ratio(char_edits, len(ref_chars))

    ref_tokens = tokenize_for_wer(reference)
    hyp_tokens = tokenize_for_wer(hypothesis)
    word_edits = edit_distance(ref_tokens, hyp_tokens)
    wer = ratio(word_edits, len(ref_tokens))

    hit_count, expected_count, hits, missed = term_hits(reference, hypothesis, domain_terms)
    term_recall = ratio(expected_count - len(missed), expected_count) if expected_count else 1.0

    return {
        **row,
        "audio_exists": audio_exists,
        "eval_status": "evaluated",
        "cer": cer,
        "wer": wer,
        "char_edits": char_edits,
        "word_edits": word_edits,
        "ref_chars": len(ref_chars),
        "ref_tokens": len(ref_tokens),
        "term_hit_count": hit_count,
        "term_expected_count": expected_count,
        "term_recall": term_recall,
        "term_hits": ";".join(hits),
        "term_missed": ";".join(missed),
    }


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def summarize(rows: list[dict[str, Any]], hypothesis_column: str) -> dict[str, Any]:
    counts = Counter(str(row["eval_status"]) for row in rows)
    evaluated = [row for row in rows if row["eval_status"] == "evaluated"]
    by_noise: dict[str, dict[str, Any]] = {}
    by_scenario: dict[str, dict[str, Any]] = {}

    for group_key, target in [("noise_condition", by_noise), ("scenario", by_scenario)]:
        for row in rows:
            key = str(row.get(group_key, "unknown"))
            bucket = target.setdefault(key, {"total": 0, "evaluated": 0, "cer_values": [], "wer_values": []})
            bucket["total"] += 1
            if row["eval_status"] == "evaluated":
                bucket["evaluated"] += 1
                bucket["cer_values"].append(float(row["cer"]))
                bucket["wer_values"].append(float(row["wer"]))

    def finalize_groups(groups: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out = {}
        for key, item in groups.items():
            out[key] = {
                "total": item["total"],
                "evaluated": item["evaluated"],
                "avg_cer": mean(item["cer_values"]),
                "avg_wer": mean(item["wer_values"]),
            }
        return out

    cer_values = [float(row["cer"]) for row in evaluated]
    wer_values = [float(row["wer"]) for row in evaluated]
    term_rows = [row for row in evaluated if int(row["term_expected_count"]) > 0]
    term_expected = sum(int(row["term_expected_count"]) for row in term_rows)
    term_hit = sum(int(row["term_hit_count"]) for row in term_rows)

    if counts.get("missing_audio", 0) > 0 and len(evaluated) == 0:
        status = "pending_audio"
    elif counts.get("missing_asr", 0) > 0 and len(evaluated) == 0:
        status = "pending_asr"
    elif counts.get("missing_audio", 0) > 0 or counts.get("missing_asr", 0) > 0:
        status = "partial"
    else:
        status = "ready"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_manifest_rows": len(rows),
        "evaluated_rows": len(evaluated),
        "missing_audio_rows": counts.get("missing_audio", 0),
        "missing_asr_rows": counts.get("missing_asr", 0),
        "avg_cer": mean(cer_values),
        "avg_wer": mean(wer_values),
        "term_expected_count": term_expected,
        "term_hit_count": term_hit,
        "term_recall": ratio(term_hit, term_expected) if term_expected else 0.0,
        "status": status,
        "hypothesis_column": hypothesis_column,
        "by_noise": finalize_groups(by_noise),
        "by_scenario": finalize_groups(by_scenario),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# ShipVoice ASR Evaluation",
        "",
        f"- Status: `{summary['status']}`",
        f"- Manifest rows: {summary['total_manifest_rows']}",
        f"- Evaluated rows: {summary['evaluated_rows']}",
        f"- Missing audio rows: {summary['missing_audio_rows']}",
        f"- Missing ASR rows: {summary['missing_asr_rows']}",
        f"- Average CER: {summary['avg_cer']:.2%}",
        f"- Average WER: {summary['avg_wer']:.2%}",
        f"- Domain-term recall: {summary['term_recall']:.2%}",
        "",
        "## Noise Breakdown",
        "",
        "| Noise | Total | Evaluated | Avg CER | Avg WER |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for noise, item in sorted(summary["by_noise"].items()):
        lines.append(
            f"| {noise} | {item['total']} | {item['evaluated']} | "
            f"{float(item['avg_cer']):.2%} | {float(item['avg_wer']):.2%} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate ASR transcripts against ShipVoice audio manifest.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "audio" / "audio_manifest.csv")
    parser.add_argument("--output-csv", type=Path, default=ROOT / "results" / "asr_eval.csv")
    parser.add_argument("--output-json", type=Path, default=ROOT / "results" / "asr_eval_summary.json")
    parser.add_argument("--output-report", type=Path, default=ROOT / "results" / "asr_eval_report.md")
    parser.add_argument("--hypothesis-column", default="asr_transcript")
    parser.add_argument("--fail-if-no-audio", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config()
    manifest_rows = read_manifest(args.manifest)
    rows = [evaluate_row(row, config.domain_terms, args.hypothesis_column) for row in manifest_rows]
    summary = summarize(rows, args.hypothesis_column)

    write_csv(args.output_csv, rows)
    args.output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(args.output_report, summary)

    print(f"Manifest rows: {summary['total_manifest_rows']}")
    print(f"Evaluated rows: {summary['evaluated_rows']}")
    print(f"Missing audio rows: {summary['missing_audio_rows']}")
    print(f"Average CER: {summary['avg_cer']:.2%}")
    print(f"Wrote {args.output_csv}")
    print(f"Wrote {args.output_json}")
    print(f"Wrote {args.output_report}")

    if args.fail_if_no_audio and summary["evaluated_rows"] == 0:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
