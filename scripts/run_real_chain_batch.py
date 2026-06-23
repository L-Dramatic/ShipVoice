from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from check_real_service_chain import llm_health_check  # noqa: E402
from shipvoice.config import load_config, load_env_file  # noqa: E402
from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def numeric(values: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for item in values:
        value = item.get(key)
        if value in {"", None}:
            continue
        out.append(float(value))
    return out


def avg(values: list[dict[str, Any]], key: str) -> float:
    nums = numeric(values, key)
    return round(sum(nums) / len(nums), 2) if nums else 0.0


def metric(metrics: dict[str, Any], key: str, fallback: str = "") -> Any:
    if key in metrics and metrics[key] not in {"", None}:
        return metrics[key]
    return metrics.get(fallback, 0) if fallback else 0


def redact_audio_output(audio_output: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(audio_output)
    audio_base64 = str(redacted.get("audio_base64", ""))
    if audio_base64:
        redacted["audio_base64_len"] = len(audio_base64)
        redacted["audio_base64_sha256"] = hashlib.sha256(audio_base64.encode("ascii")).hexdigest()
        redacted["audio_base64"] = "<redacted>"
    audio_segments = redacted.get("audio_segments")
    if isinstance(audio_segments, list) and audio_segments:
        segment_values = [str(item) for item in audio_segments]
        redacted["audio_segments_count"] = len(segment_values)
        redacted["audio_segments_base64_lens"] = [len(item) for item in segment_values]
        redacted["audio_segments_sha256"] = [
            hashlib.sha256(item.encode("ascii")).hexdigest() for item in segment_values
        ]
        redacted["audio_segments"] = ["<redacted>"] * len(segment_values)
    return redacted


async def run_sample(pipeline: VoiceQAPipeline, row: dict[str, str], *, mode: str) -> dict[str, Any]:
    sample_id = row.get("id", "").strip()
    relative_audio_path = row.get("audio_path", "").strip()
    audio_path = ROOT / relative_audio_path
    if not audio_path.exists():
        return {
            "sample_id": sample_id,
            "status": "error",
            "audio_path": str(audio_path),
            "reference_transcript": row.get("transcript", ""),
            "error": f"audio file not found: {audio_path}",
        }

    started_at = datetime.now(timezone.utc).isoformat()
    result = await pipeline.run_once(
        "",
        audio_bytes=audio_path.read_bytes(),
        audio_name=audio_path.name,
        question_id=sample_id or "unknown",
        category=row.get("scenario", "real_chain"),
        mode=mode,
    )
    metrics = result.metrics.to_row()
    provider_status = result.provider_status
    return {
        "sample_id": sample_id,
        "status": "ok",
        "started_at": started_at,
        "audio_path": relative_audio_path,
        "reference_transcript": row.get("transcript", ""),
        "transcript": result.transcript,
        "gate_label": result.gate.label,
        "gate_allowed": result.gate.allowed,
        "asr_ms": metric(metrics, "asr_ms"),
        "retrieval_ms": metric(metrics, "retrieval_ms"),
        "llm_first_delta_ms": metric(metrics, "llm_first_delta_ms"),
        "llm_complete_ms": metric(metrics, "llm_complete_ms", "llm_first_token_ms"),
        "tts_complete_ms": metric(metrics, "tts_complete_ms", "tts_first_audio_ms"),
        "server_first_audio_chunk_ready_ms": metric(metrics, "server_first_audio_chunk_ready_ms"),
        "server_audio_payload_ready_ms": metric(metrics, "server_audio_payload_ready_ms", "first_audio_ms"),
        "server_audio_stream_complete_ms": metric(metrics, "server_audio_stream_complete_ms"),
        "streamed_audio_segments": metric(metrics, "streamed_audio_segments"),
        "total_ms": metric(metrics, "total_ms"),
        "evidence_count": len(result.evidence),
        "evidence_ids": [hit.record_id for hit in result.evidence],
        "response_mode": provider_status.get("response_mode", ""),
        "timing_source": provider_status.get("timing_source", ""),
        "providers": provider_status,
        "answer_preview": result.answer[:240],
        "answer_chars": len(result.answer),
        "audio_output": redact_audio_output(result.audio_output.__dict__),
    }


def select_rows(rows: list[dict[str, str]], *, limit: int, split: str, sample_ids: set[str]) -> list[dict[str, str]]:
    selected = []
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


def build_summary(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    samples: list[dict[str, Any]],
    llm_health: dict[str, Any],
) -> dict[str, Any]:
    ok_samples = [item for item in samples if item.get("status") == "ok"]
    failed_samples = [item for item in samples if item.get("status") != "ok"]
    provider_status = ok_samples[0].get("providers", {}) if ok_samples else {}
    timing_source = ok_samples[0].get("timing_source") or provider_status.get("timing_source", "")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "env_file": os.environ.get("SHIPVOICE_ENV_FILE", ""),
        "manifest": str(args.manifest),
        "output_dir": str(output_dir),
        "mode": args.mode,
        "requested_limit": args.limit,
        "num_samples": len(ok_samples),
        "num_failed": len(failed_samples),
        "asr_request_reference_sent": False,
        "timing_source": timing_source or "server_audio_payload_ready",
        "response_mode": provider_status.get("response_mode", ""),
        "avg_asr_ms": avg(ok_samples, "asr_ms"),
        "avg_retrieval_ms": avg(ok_samples, "retrieval_ms"),
        "avg_llm_first_delta_ms": avg(ok_samples, "llm_first_delta_ms"),
        "avg_llm_complete_ms": avg(ok_samples, "llm_complete_ms"),
        "avg_tts_complete_ms": avg(ok_samples, "tts_complete_ms"),
        "avg_server_first_audio_chunk_ready_ms": avg(ok_samples, "server_first_audio_chunk_ready_ms"),
        "avg_server_audio_payload_ready_ms": avg(ok_samples, "server_audio_payload_ready_ms"),
        "avg_server_audio_stream_complete_ms": avg(ok_samples, "server_audio_stream_complete_ms"),
        "avg_streamed_audio_segments": avg(ok_samples, "streamed_audio_segments"),
        "avg_total_ms": avg(ok_samples, "total_ms"),
        "llm_health": llm_health,
        "llm_require_lora": bool(args.require_lora),
        "llm_required_model_substring": args.require_llm_model_substring,
        "execution_profile": provider_status.get("execution_profile", ""),
        "asr_provider": provider_status.get("asr", ""),
        "llm_provider": provider_status.get("llm", ""),
        "tts_provider": provider_status.get("tts", ""),
        "samples": samples,
    }


async def run_batch(args: argparse.Namespace) -> dict[str, Any]:
    if args.env_file:
        load_env_file(args.env_file)

    args.require_lora = args.require_lora or os.environ.get("SHIPVOICE_REQUIRE_LORA", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if args.require_lora and not args.require_llm_model_substring:
        args.require_llm_model_substring = os.environ.get("SHIPVOICE_REQUIRE_LLM_MODEL_SUBSTRING", "shipvoice")

    llm_health: dict[str, Any] = {}
    config = load_config()
    llm_base_url = os.environ.get("SHIPVOICE_OPENAI_BASE_URL", str(config.llm.get("openai_base_url", ""))).strip()
    if llm_base_url:
        llm_health = llm_health_check(
            llm_base_url,
            api_key=os.environ.get("SHIPVOICE_OPENAI_API_KEY", ""),
            required_model_substring=args.require_llm_model_substring,
            require_lora=args.require_lora,
            required_adapter_sha256=os.environ.get("SHIPVOICE_LORA_ADAPTER_SHA256", ""),
        )

    rows = read_manifest(args.manifest)
    selected = select_rows(
        rows,
        limit=args.limit,
        split=args.split,
        sample_ids={item.strip() for item in args.sample_ids.split(",") if item.strip()},
    )
    if not selected:
        raise SystemExit("no runnable audio rows selected")

    pipeline = VoiceQAPipeline()
    samples: list[dict[str, Any]] = []
    for row in selected:
        sample_id = row.get("id", "")
        try:
            sample = await run_sample(pipeline, row, mode=args.mode)
        except Exception as exc:  # noqa: BLE001
            sample = {
                "sample_id": sample_id,
                "status": "error",
                "audio_path": row.get("audio_path", ""),
                "reference_transcript": row.get("transcript", ""),
                "error": str(exc),
            }
            if args.fail_fast:
                samples.append(sample)
                break
        samples.append(sample)
        print(json.dumps({"sample_id": sample_id, "status": sample["status"]}, ensure_ascii=False))

    output_dir = args.output_dir
    if output_dir is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = ROOT / "results" / f"remote_real_chain_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    samples_path = output_dir / "samples.jsonl"
    samples_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in samples) + "\n", encoding="utf-8")
    summary = build_summary(args=args, output_dir=output_dir, samples=samples, llm_health=llm_health)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if summary["num_failed"] and not args.allow_failures:
        raise SystemExit(f"{summary['num_failed']} samples failed; see {samples_path}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a batch real ASR/LLM/TTS chain validation from the audio manifest.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "audio" / "audio_manifest.csv")
    parser.add_argument("--env-file", default=os.environ.get("SHIPVOICE_ENV_FILE", ""))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--mode", default="full", choices=["baseline", "streaming", "rag", "guarded", "full"])
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--split", default="test")
    parser.add_argument("--sample-ids", default="", help="Comma-separated sample ids. Overrides split/limit filtering.")
    parser.add_argument("--require-lora", action="store_true", default=False)
    parser.add_argument("--require-llm-model-substring", default=os.environ.get("SHIPVOICE_REQUIRE_LLM_MODEL_SUBSTRING", ""))
    parser.add_argument("--allow-failures", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()

    summary = asyncio.run(run_batch(args))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
