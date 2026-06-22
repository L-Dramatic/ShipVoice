from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def normalize(text: str) -> str:
    return "".join(str(text).split()).lower()


def validate_rows(rows: list[dict], name: str) -> list[str]:
    errors: list[str] = []
    ids = [row.get("id", "") for row in rows]
    duplicate_ids = [item for item, count in Counter(ids).items() if item and count > 1]
    if duplicate_ids:
        errors.append(f"{name}: duplicate ids: {duplicate_ids[:10]}")
    inputs = [normalize(row.get("input", "")) for row in rows]
    duplicate_inputs = [item for item, count in Counter(inputs).items() if item and count > 1]
    if duplicate_inputs:
        errors.append(f"{name}: duplicate normalized inputs: {len(duplicate_inputs)}")
    required = ["instruction", "input", "output", "category", "split"]
    for index, row in enumerate(rows, 1):
        for key in required:
            if not str(row.get(key, "")).strip():
                errors.append(f"{name}:{index}: missing {key}")
        if len(str(row.get("output", ""))) < 30:
            errors.append(f"{name}:{index}: output too short")
    return errors


def summarize(rows: list[dict]) -> dict:
    return {
        "total": len(rows),
        "by_category": dict(sorted(Counter(row.get("category", "") for row in rows).items())),
        "avg_input_chars": round(sum(len(row.get("input", "")) for row in rows) / max(len(rows), 1), 2),
        "avg_output_chars": round(sum(len(row.get("output", "")) for row in rows) / max(len(rows), 1), 2),
        "min_output_chars": min((len(row.get("output", "")) for row in rows), default=0),
        "max_output_chars": max((len(row.get("output", "")) for row in rows), default=0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate ShipVoice SFT train/eval JSONL files.")
    parser.add_argument("--train", default="data/training/shipvoice_sft_train_expanded.jsonl")
    parser.add_argument("--eval", default="data/training/shipvoice_sft_eval_holdout.jsonl")
    parser.add_argument("--min-train", type=int, default=1000)
    parser.add_argument("--min-eval", type=int, default=150)
    parser.add_argument("--out", default="results/expanded_sft_validation.json")
    args = parser.parse_args()

    train_path = Path(args.train)
    eval_path = Path(args.eval)
    train_rows = read_jsonl(train_path)
    eval_rows = read_jsonl(eval_path)

    errors = []
    if len(train_rows) < args.min_train:
        errors.append(f"train has {len(train_rows)} rows, expected >= {args.min_train}")
    if len(eval_rows) < args.min_eval:
        errors.append(f"eval has {len(eval_rows)} rows, expected >= {args.min_eval}")
    errors.extend(validate_rows(train_rows, "train"))
    errors.extend(validate_rows(eval_rows, "eval"))

    train_inputs = {normalize(row["input"]) for row in train_rows}
    eval_inputs = {normalize(row["input"]) for row in eval_rows}
    overlap = train_inputs & eval_inputs
    if overlap:
        errors.append(f"train/eval exact normalized input overlap: {len(overlap)}")

    payload = {
        "ok": not errors,
        "errors": errors,
        "train": summarize(train_rows),
        "eval": summarize(eval_rows),
        "train_eval_exact_input_overlap": len(overlap),
        "train_path": str(train_path),
        "eval_path": str(eval_path),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
