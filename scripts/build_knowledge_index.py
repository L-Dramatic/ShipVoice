from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", text.lower())
    chars = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    bigrams = ["".join(chars[i : i + 2]) for i in range(max(0, len(chars) - 1))]
    return words + bigrams


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            for key in ["id", "title", "text"]:
                if not item.get(key):
                    raise ValueError(f"{path}:{line_no} missing {key}")
            item.setdefault("tags", [])
            docs.append(item)
    return docs


def build_index(docs: list[dict[str, Any]]) -> dict[str, Any]:
    inverted: dict[str, list[dict[str, int]]] = defaultdict(list)
    document_rows: list[dict[str, Any]] = []
    for idx, item in enumerate(docs):
        joined = " ".join([item["title"], item["text"], " ".join(item.get("tags", []))])
        term_counts = Counter(tokenize(joined))
        for term, count in term_counts.items():
            inverted[term].append({"doc": idx, "count": count})
        document_rows.append(
            {
                "id": item["id"],
                "title": item["title"],
                "tags": item.get("tags", []),
                "text": item["text"],
                "token_count": sum(term_counts.values()),
            }
        )
    return {
        "version": 1,
        "document_count": len(document_rows),
        "documents": document_rows,
        "inverted": dict(inverted),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local ship safety RAG index.")
    parser.add_argument("--corpus", default=str(ROOT / "data" / "knowledge" / "ship_safety_corpus.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "data" / "knowledge" / "ship_safety_index.json"))
    args = parser.parse_args()

    corpus_path = Path(args.corpus)
    out_path = Path(args.out)
    docs = read_jsonl(corpus_path)
    index = build_index(docs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"indexed {len(docs)} documents -> {out_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

