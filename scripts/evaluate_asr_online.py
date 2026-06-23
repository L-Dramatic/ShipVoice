from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_asr_transcripts import evaluate_row, read_manifest, summarize, write_csv, write_report  # noqa: E402
from shipvoice.config import load_config, load_env_file  # noqa: E402


def http_json(method: str, url: str, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def select_rows(rows: list[dict[str, str]], *, split: str, limit: int, sample_ids: set[str]) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in rows:
        if sample_ids and row.get("id", "") not in sample_ids:
            continue
        if split and row.get("split", "") != split:
            continue
        audio_path = ROOT / row.get("audio_path", "")
        if not audio_path.exists():
            continue
        selected.append(row)
        if limit and len(selected) >= limit:
            break
    return selected


def first_text(payload: dict[str, Any]) -> tuple[str, str]:
    raw = str(
        payload.get("raw_transcript")
        or payload.get("raw_text")
        or payload.get("text_raw")
        or payload.get("transcript_raw")
        or ""
    ).strip()
    corrected = str(
        payload.get("transcript")
        or payload.get("text")
        or payload.get("postprocess_transcript")
        or payload.get("corrected_transcript")
        or raw
    ).strip()
    return raw or corrected, corrected or raw


def run_online_asr(args: argparse.Namespace) -> dict[str, Any]:
    if args.env_file:
        load_env_file(args.env_file)
    endpoint = args.endpoint or os.environ.get("SHIPVOICE_ASR_ENDPOINT", "")
    if not endpoint:
        raise SystemExit("ASR endpoint is required; pass --endpoint or set SHIPVOICE_ASR_ENDPOINT")

    config = load_config()
    manifest_rows = read_manifest(args.manifest)
    rows = select_rows(
        manifest_rows,
        split=args.split,
        limit=args.limit,
        sample_ids={item.strip() for item in args.sample_ids.split(",") if item.strip()},
    )
    if not rows:
        raise SystemExit("no runnable audio rows selected")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = args.output_dir / "asr_outputs.jsonl"
    evaluated_rows: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    with raw_path.open("w", encoding="utf-8") as raw_handle:
        for index, row in enumerate(rows, start=1):
            sample_id = row.get("id", "")
            audio_path = ROOT / row["audio_path"]
            started = time.perf_counter()
            payload = {
                "audio_base64": base64.b64encode(audio_path.read_bytes()).decode("ascii"),
                "audio_name": audio_path.name,
            }
            status = "ok"
            error = ""
            response: dict[str, Any] = {}
            try:
                response = http_json("POST", endpoint, payload, timeout=args.timeout)
            except Exception as exc:  # noqa: BLE001
                status = "error"
                error = str(exc)
            latency_ms = round((time.perf_counter() - started) * 1000)
            raw_text, corrected_text = first_text(response)
            record = {
                "sample_id": sample_id,
                "status": status,
                "error": error,
                "audio_path": row.get("audio_path", ""),
                "reference_transcript": row.get("transcript", ""),
                "raw_transcript": raw_text,
                "postprocess_transcript": corrected_text,
                "latency_ms": latency_ms,
                "response": response,
            }
            raw_records.append(record)
            raw_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            eval_input = {**row, "online_raw_transcript": raw_text, "online_postprocess_transcript": corrected_text}
            evaluated_rows.append(evaluate_row(eval_input, config.domain_terms, args.hypothesis_column))
            print(json.dumps({"sample_id": sample_id, "status": status, "index": index, "latency_ms": latency_ms}, ensure_ascii=False))
            if status != "ok" and args.fail_fast:
                break

    summary = summarize(evaluated_rows, args.hypothesis_column)
    summary.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
            "manifest": str(args.manifest),
            "output_dir": str(args.output_dir),
            "mode": "online_asr_no_reference_hint",
            "num_requested": len(rows),
            "num_ok": sum(1 for item in raw_records if item["status"] == "ok"),
            "num_failed_requests": sum(1 for item in raw_records if item["status"] != "ok"),
            "avg_asr_latency_ms": round(
                sum(float(item["latency_ms"]) for item in raw_records) / len(raw_records), 2
            )
            if raw_records
            else 0.0,
            "raw_outputs_path": str(raw_path),
        }
    )
    write_csv(args.output_dir / "asr_eval_online.csv", evaluated_rows)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(args.output_dir / "report.md", summary)
    if summary["num_failed_requests"] and not args.allow_failures:
        raise SystemExit(f"{summary['num_failed_requests']} ASR requests failed; see {raw_path}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run online ASR against audio files without sending transcript hints.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "audio" / "audio_manifest.csv")
    parser.add_argument("--env-file", default=os.environ.get("SHIPVOICE_ENV_FILE", ""))
    parser.add_argument("--endpoint", default=os.environ.get("SHIPVOICE_ASR_ENDPOINT", ""))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "asr_online_20260623")
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--sample-ids", default="")
    parser.add_argument("--hypothesis-column", default="online_postprocess_transcript")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--allow-failures", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    summary = run_online_asr(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
