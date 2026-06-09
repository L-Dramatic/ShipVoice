from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess


ROOT = Path(__file__).resolve().parents[1]


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch ASR for ShipVoice audio manifest with FunASR/SenseVoice.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "audio" / "audio_manifest.csv")
    parser.add_argument("--output-summary", type=Path, default=ROOT / "results" / "remote_asr_run_summary.json")
    parser.add_argument("--model", default="iic/SenseVoiceSmall")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--batch-size-s", type=int, default=60)
    parser.add_argument("--merge-length-s", type=int, default=15)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_manifest(args.manifest)

    model = AutoModel(
        model=args.model,
        vad_model="fsmn-vad",
        vad_kwargs={"max_single_segment_time": 30000},
        device=args.device,
    )

    processed = 0
    skipped = 0
    failed = 0
    failures: list[dict[str, str]] = []
    started = time.perf_counter()

    for row in rows:
        audio_rel = row.get("audio_path", "").strip()
        audio_path = ROOT / audio_rel
        existing = row.get("asr_transcript", "").strip()

        if existing and not args.overwrite:
            skipped += 1
            continue
        if not audio_rel or not audio_path.exists():
            failed += 1
            row["status"] = "missing_audio"
            failures.append({"id": row.get("id", ""), "reason": f"missing audio: {audio_rel}"})
            continue

        item_started = time.perf_counter()
        try:
            result = model.generate(
                input=str(audio_path),
                cache={},
                language=args.language,
                use_itn=True,
                batch_size_s=args.batch_size_s,
                merge_vad=True,
                merge_length_s=args.merge_length_s,
            )
            raw_text = ""
            if result and isinstance(result, list):
                raw_text = str(result[0].get("text", ""))
            text = rich_transcription_postprocess(raw_text).strip()
            row["asr_transcript"] = text
            row["asr_provider"] = "funasr_sensevoice"
            row["status"] = "transcribed" if text else "asr_empty"
            row["notes"] = f"{row.get('notes', '').strip()} | asr_sec={time.perf_counter() - item_started:.2f}".strip(" |")
            processed += 1
            print(f"[OK] {row.get('id', '')}: {text}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            row["status"] = "asr_failed"
            failures.append({"id": row.get("id", ""), "reason": str(exc)})
            print(f"[FAIL] {row.get('id', '')}: {exc}", file=sys.stderr)

        write_manifest(args.manifest, rows)

    write_manifest(args.manifest, rows)

    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(args.manifest),
        "model": args.model,
        "device": args.device,
        "language": args.language,
        "batch_size_s": args.batch_size_s,
        "merge_length_s": args.merge_length_s,
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "failures": failures,
    }
    args.output_summary.parent.mkdir(parents=True, exist_ok=True)
    args.output_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
