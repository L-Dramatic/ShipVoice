from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply ShipVoice domain-aware ASR postprocess rules.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "audio" / "audio_manifest.csv")
    parser.add_argument("--rules", type=Path, default=ROOT / "configs" / "asr_postprocess_rules.json")
    parser.add_argument("--source-column", default="asr_transcript")
    parser.add_argument("--raw-column", default="asr_transcript_raw")
    parser.add_argument("--target-column", default="asr_transcript")
    parser.add_argument("--provider-column", default="asr_provider")
    parser.add_argument("--hits-column", default="asr_postprocess_hits")
    parser.add_argument("--summary-json", type=Path, default=ROOT / "results" / "asr_postprocess_summary.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_csv(args.manifest)
    rule_data = json.loads(args.rules.read_text(encoding="utf-8"))
    replacements: list[dict[str, str]] = list(rule_data.get("replacements", []))

    changed_rows = 0
    changed_spans = 0
    hit_counter: dict[str, int] = {}
    examples: list[dict[str, Any]] = []

    for row in rows:
        original = row.get(args.raw_column, "").strip() or row.get(args.source_column, "").strip()
        corrected = original
        hits: list[str] = []

        if original:
            row[args.raw_column] = original

        for item in replacements:
            pattern = str(item["pattern"])
            replacement = str(item["replacement"])
            category = str(item.get("category", "rule"))
            if pattern in corrected:
                count = corrected.count(pattern)
                corrected = corrected.replace(pattern, replacement)
                hit_key = f"{pattern}->{replacement}"
                hits.append(hit_key)
                hit_counter[hit_key] = hit_counter.get(hit_key, 0) + count
                changed_spans += count

        row[args.target_column] = corrected
        row[args.hits_column] = ";".join(hits)
        provider = row.get(args.provider_column, "").strip()
        if provider and "+term_rules" not in provider:
            row[args.provider_column] = provider + "+term_rules"
        elif not provider:
            row[args.provider_column] = "term_rules_only"

        if corrected != original:
            changed_rows += 1
            if len(examples) < 12:
                examples.append(
                    {
                        "id": row.get("id", ""),
                        "raw": original,
                        "corrected": corrected,
                        "hits": hits,
                    }
                )

    write_csv(args.manifest, rows)

    summary = {
        "version": str(rule_data.get("version", "unknown")),
        "manifest": str(args.manifest),
        "rows_total": len(rows),
        "rows_changed": changed_rows,
        "replacements_applied": changed_spans,
        "rule_hits": hit_counter,
        "examples": examples,
    }
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Rows changed: {changed_rows}/{len(rows)}")
    print(f"Replacement spans: {changed_spans}")
    print(f"Wrote {args.summary_json}")


if __name__ == "__main__":
    main()
