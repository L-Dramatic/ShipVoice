from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from check_real_service_chain import llm_health_check  # noqa: E402
from compare_real_chain_batches import percentile, stats  # noqa: E402
from run_real_chain_batch import read_manifest, run_sample, select_rows  # noqa: E402
from shipvoice.config import load_config, load_env_file  # noqa: E402
from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402


def metric_value(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    if value in {"", None}:
        return 0.0
    return float(value)


def first_audio_ready(row: dict[str, Any]) -> float:
    streamed = metric_value(row, "server_first_audio_chunk_ready_ms")
    if streamed > 0:
        return streamed
    return metric_value(row, "server_audio_payload_ready_ms")


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [row for row in rows if row.get("status") == "ok"]
    gate_allowed = [row for row in ok if row.get("gate_allowed") is True]
    for row in ok:
        row["first_audio_ready_ms"] = first_audio_ready(row)
    return {
        "num_samples": len(ok),
        "num_failed": len(rows) - len(ok),
        "num_gate_allowed": len(gate_allowed),
        "all_ok": {
            "asr_ms": stats(ok, "asr_ms"),
            "llm_first_delta_ms": stats(ok, "llm_first_delta_ms"),
            "llm_complete_ms": stats(ok, "llm_complete_ms"),
            "first_audio_ready_ms": stats(ok, "first_audio_ready_ms"),
            "server_audio_stream_complete_ms": stats(ok, "server_audio_stream_complete_ms"),
            "total_ms": stats(ok, "total_ms"),
            "streamed_audio_segments": stats(ok, "streamed_audio_segments"),
        },
        "gate_allowed": {
            "asr_ms": stats(gate_allowed, "asr_ms"),
            "llm_first_delta_ms": stats(gate_allowed, "llm_first_delta_ms"),
            "llm_complete_ms": stats(gate_allowed, "llm_complete_ms"),
            "first_audio_ready_ms": stats(gate_allowed, "first_audio_ready_ms"),
            "server_audio_stream_complete_ms": stats(gate_allowed, "server_audio_stream_complete_ms"),
            "total_ms": stats(gate_allowed, "total_ms"),
            "streamed_audio_segments": stats(gate_allowed, "streamed_audio_segments"),
        },
    }


def paired_deltas(rows: list[dict[str, Any]], *, gate_allowed_only: bool) -> dict[str, Any]:
    grouped: dict[tuple[int, str], dict[str, dict[str, Any]]] = {}
    for row in rows:
        if row.get("status") != "ok":
            continue
        key = (int(row.get("repeat", 0)), str(row.get("sample_id", "")))
        grouped.setdefault(key, {})[str(row.get("mode", ""))] = row

    deltas: list[float] = []
    pair_ids: list[str] = []
    for (repeat, sample_id), pair in sorted(grouped.items()):
        baseline = pair.get("baseline")
        streaming = pair.get("streaming")
        if not baseline or not streaming:
            continue
        if gate_allowed_only and not (baseline.get("gate_allowed") is True and streaming.get("gate_allowed") is True):
            continue
        base_ready = first_audio_ready(baseline)
        stream_ready = first_audio_ready(streaming)
        if base_ready <= 0 or stream_ready <= 0:
            continue
        deltas.append(base_ready - stream_ready)
        pair_ids.append(f"r{repeat}:{sample_id}")
    return {
        "matched_count": len(deltas),
        "matched_pair_ids": pair_ids,
        "streaming_first_audio_faster_count": sum(1 for item in deltas if item > 0),
        "streaming_first_audio_not_faster_count": sum(1 for item in deltas if item <= 0),
        "first_audio_ready_ms_saved": {
            "avg": round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
            "p50": percentile(deltas, 0.50),
            "p90": percentile(deltas, 0.90),
            "p95": percentile(deltas, 0.95),
            "min": round(min(deltas), 2) if deltas else 0.0,
            "max": round(max(deltas), 2) if deltas else 0.0,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    baseline_allowed = report["modes"]["baseline"]["gate_allowed"]
    streaming_allowed = report["modes"]["streaming"]["gate_allowed"]
    deltas = report["paired_deltas"]["gate_allowed"]["first_audio_ready_ms_saved"]
    lines = [
        "# ShipVoice Repeated Real Chain Experiment",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Repeats: {report['repeats']}",
        f"- Modes: {', '.join(report['modes_requested'])}",
        f"- Selected samples: {report['selected_samples']}",
        f"- Total ok runs: {report['num_ok']} / {report['num_runs']}",
        f"- Gate-allowed matched pairs: {report['paired_deltas']['gate_allowed']['matched_count']}",
        "",
        "## Gate-Allowed Latency",
        "",
        "| Metric | Baseline avg | Baseline p50 | Streaming avg | Streaming p50 | Streaming p90 | Streaming p95 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            "| First audio ready ms | "
            f"{baseline_allowed['first_audio_ready_ms']['avg']} | "
            f"{baseline_allowed['first_audio_ready_ms']['p50']} | "
            f"{streaming_allowed['first_audio_ready_ms']['avg']} | "
            f"{streaming_allowed['first_audio_ready_ms']['p50']} | "
            f"{streaming_allowed['first_audio_ready_ms']['p90']} | "
            f"{streaming_allowed['first_audio_ready_ms']['p95']} |"
        ),
        (
            "| LLM first delta ms | "
            f"{baseline_allowed['llm_first_delta_ms']['avg']} | "
            f"{baseline_allowed['llm_first_delta_ms']['p50']} | "
            f"{streaming_allowed['llm_first_delta_ms']['avg']} | "
            f"{streaming_allowed['llm_first_delta_ms']['p50']} | "
            f"{streaming_allowed['llm_first_delta_ms']['p90']} | "
            f"{streaming_allowed['llm_first_delta_ms']['p95']} |"
        ),
        (
            "| Streamed audio segments | "
            f"{baseline_allowed['streamed_audio_segments']['avg']} | "
            f"{baseline_allowed['streamed_audio_segments']['p50']} | "
            f"{streaming_allowed['streamed_audio_segments']['avg']} | "
            f"{streaming_allowed['streamed_audio_segments']['p50']} | "
            f"{streaming_allowed['streamed_audio_segments']['p90']} | "
            f"{streaming_allowed['streamed_audio_segments']['p95']} |"
        ),
        "",
        "## First Audio Saved",
        "",
        f"- Gate-allowed average saved: {deltas['avg']} ms.",
        f"- Gate-allowed p50/p90/p95 saved: {deltas['p50']} / {deltas['p90']} / {deltas['p95']} ms.",
        (
            "- Gate-allowed faster count: "
            f"{report['paired_deltas']['gate_allowed']['streaming_first_audio_faster_count']} / "
            f"{report['paired_deltas']['gate_allowed']['matched_count']}."
        ),
    ]
    return "\n".join(lines) + "\n"


async def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    if args.env_file:
        load_env_file(args.env_file)

    require_lora = args.require_lora or os.environ.get("SHIPVOICE_REQUIRE_LORA", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    required_model_substring = args.require_llm_model_substring or os.environ.get(
        "SHIPVOICE_REQUIRE_LLM_MODEL_SUBSTRING", "shipvoice" if require_lora else ""
    )

    config = load_config()
    llm_base_url = os.environ.get("SHIPVOICE_OPENAI_BASE_URL", str(config.llm.get("openai_base_url", ""))).strip()
    llm_health: dict[str, Any] = {}
    if llm_base_url:
        llm_health = llm_health_check(
            llm_base_url,
            api_key=os.environ.get("SHIPVOICE_OPENAI_API_KEY", ""),
            required_model_substring=required_model_substring,
            require_lora=require_lora,
            required_adapter_sha256=os.environ.get("SHIPVOICE_LORA_ADAPTER_SHA256", ""),
        )

    selected = select_rows(
        read_manifest(args.manifest),
        limit=args.limit,
        split=args.split,
        sample_ids={item.strip() for item in args.sample_ids.split(",") if item.strip()},
    )
    if not selected:
        raise SystemExit("no runnable audio rows selected")

    modes = [item.strip() for item in args.modes.split(",") if item.strip()]
    plan: list[dict[str, Any]] = []
    for repeat in range(1, args.repeats + 1):
        for mode in modes:
            for row in selected:
                plan.append({"repeat": repeat, "mode": mode, "row": row})
    rng = random.Random(args.seed)
    if args.shuffle:
        rng.shuffle(plan)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    samples_path = args.output_dir / "samples.jsonl"
    pipeline = VoiceQAPipeline()
    samples: list[dict[str, Any]] = []
    with samples_path.open("w", encoding="utf-8") as handle:
        for index, item in enumerate(plan, start=1):
            row = item["row"]
            mode = item["mode"]
            repeat = int(item["repeat"])
            sample_id = row.get("id", "")
            try:
                sample = await run_sample(pipeline, row, mode=mode)
            except Exception as exc:  # noqa: BLE001
                sample = {
                    "sample_id": sample_id,
                    "status": "error",
                    "audio_path": row.get("audio_path", ""),
                    "reference_transcript": row.get("transcript", ""),
                    "error": str(exc),
                }
                if args.fail_fast:
                    sample.update({"repeat": repeat, "mode": mode, "sequence": index})
                    samples.append(sample)
                    handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
                    break
            sample.update({"repeat": repeat, "mode": mode, "sequence": index})
            samples.append(sample)
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
            handle.flush()
            print(json.dumps({"sequence": index, "total": len(plan), "repeat": repeat, "mode": mode, "sample_id": sample_id, "status": sample["status"]}, ensure_ascii=False))

    by_mode = {mode: [row for row in samples if row.get("mode") == mode] for mode in modes}
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "env_file": os.environ.get("SHIPVOICE_ENV_FILE", ""),
        "manifest": str(args.manifest),
        "output_dir": str(args.output_dir),
        "samples_path": str(samples_path),
        "repeats": args.repeats,
        "seed": args.seed,
        "shuffle": args.shuffle,
        "modes_requested": modes,
        "selected_samples": len(selected),
        "selected_sample_ids": [row.get("id", "") for row in selected],
        "num_runs": len(samples),
        "num_ok": sum(1 for row in samples if row.get("status") == "ok"),
        "num_failed": sum(1 for row in samples if row.get("status") != "ok"),
        "llm_health": llm_health,
        "llm_require_lora": require_lora,
        "llm_required_model_substring": required_model_substring,
        "llm_required_adapter_sha256": os.environ.get("SHIPVOICE_LORA_ADAPTER_SHA256", ""),
        "modes": {mode: summarize_rows(rows) for mode, rows in by_mode.items()},
        "paired_deltas": {
            "all_ok": paired_deltas(samples, gate_allowed_only=False),
            "gate_allowed": paired_deltas(samples, gate_allowed_only=True),
        },
    }
    (args.output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "summary.md").write_text(render_markdown(report), encoding="utf-8")
    if report["num_failed"] and not args.allow_failures:
        raise SystemExit(f"{report['num_failed']} runs failed; see {samples_path}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run repeated real baseline/streaming paired experiment.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "audio" / "audio_manifest.csv")
    parser.add_argument("--env-file", default=os.environ.get("SHIPVOICE_ENV_FILE", ""))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "server_real_repeated_20260623")
    parser.add_argument("--modes", default="baseline,streaming")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--split", default="test")
    parser.add_argument("--sample-ids", default="")
    parser.add_argument("--seed", type=int, default=20260623)
    parser.add_argument("--shuffle", action="store_true", default=True)
    parser.add_argument("--no-shuffle", action="store_false", dest="shuffle")
    parser.add_argument("--require-lora", action="store_true", default=False)
    parser.add_argument("--require-llm-model-substring", default=os.environ.get("SHIPVOICE_REQUIRE_LLM_MODEL_SUBSTRING", ""))
    parser.add_argument("--allow-failures", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(run_experiment(args))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
