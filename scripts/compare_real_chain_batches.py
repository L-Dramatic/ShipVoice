from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def to_float(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * pct
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def stats(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    values = [value for row in rows if (value := to_float(row.get(key))) is not None]
    return {
        "count": len(values),
        "avg": round(sum(values) / len(values), 2) if values else 0.0,
        "p50": percentile(values, 0.50),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "min": round(min(values), 2) if values else 0.0,
        "max": round(max(values), 2) if values else 0.0,
    }


def first_audio_ready(row: dict[str, Any]) -> float:
    streamed = to_float(row.get("server_first_audio_chunk_ready_ms"))
    if streamed and streamed > 0:
        return streamed
    return to_float(row.get("server_audio_payload_ready_ms")) or 0.0


def summarize_mode(rows: list[dict[str, Any]], *, mode: str) -> dict[str, Any]:
    ok = [row for row in rows if row.get("status") == "ok"]
    gate_allowed = [row for row in ok if row.get("gate_allowed") is True]
    first_audio_rows = [dict(row, first_audio_ready_ms=first_audio_ready(row)) for row in ok]
    allowed_first_audio_rows = [
        dict(row, first_audio_ready_ms=first_audio_ready(row)) for row in gate_allowed
    ]
    return {
        "mode": mode,
        "num_samples": len(ok),
        "num_failed": len(rows) - len(ok),
        "num_gate_allowed": len(gate_allowed),
        "num_streamed_segments_samples": sum(
            1 for row in ok if (to_float(row.get("streamed_audio_segments")) or 0) > 0
        ),
        "all_ok": {
            "asr_ms": stats(ok, "asr_ms"),
            "llm_first_delta_ms": stats(ok, "llm_first_delta_ms"),
            "llm_complete_ms": stats(ok, "llm_complete_ms"),
            "first_audio_ready_ms": stats(first_audio_rows, "first_audio_ready_ms"),
            "server_audio_stream_complete_ms": stats(ok, "server_audio_stream_complete_ms"),
            "total_ms": stats(ok, "total_ms"),
            "streamed_audio_segments": stats(ok, "streamed_audio_segments"),
        },
        "gate_allowed": {
            "asr_ms": stats(gate_allowed, "asr_ms"),
            "llm_first_delta_ms": stats(gate_allowed, "llm_first_delta_ms"),
            "llm_complete_ms": stats(gate_allowed, "llm_complete_ms"),
            "first_audio_ready_ms": stats(allowed_first_audio_rows, "first_audio_ready_ms"),
            "server_audio_stream_complete_ms": stats(gate_allowed, "server_audio_stream_complete_ms"),
            "total_ms": stats(gate_allowed, "total_ms"),
            "streamed_audio_segments": stats(gate_allowed, "streamed_audio_segments"),
        },
    }


def matched_deltas(
    baseline_rows: list[dict[str, Any]],
    streaming_rows: list[dict[str, Any]],
    *,
    gate_allowed_only: bool,
) -> dict[str, Any]:
    baseline_by_id = {row.get("sample_id"): row for row in baseline_rows if row.get("status") == "ok"}
    streaming_by_id = {row.get("sample_id"): row for row in streaming_rows if row.get("status") == "ok"}
    deltas: list[float] = []
    matched_ids: list[str] = []
    for sample_id, base_row in baseline_by_id.items():
        stream_row = streaming_by_id.get(sample_id)
        if not stream_row:
            continue
        if gate_allowed_only and not (base_row.get("gate_allowed") is True and stream_row.get("gate_allowed") is True):
            continue
        base_ready = first_audio_ready(base_row)
        stream_ready = first_audio_ready(stream_row)
        if base_ready <= 0 or stream_ready <= 0:
            continue
        deltas.append(base_ready - stream_ready)
        matched_ids.append(str(sample_id))
    wins = sum(1 for item in deltas if item > 0)
    return {
        "matched_count": len(deltas),
        "matched_sample_ids": matched_ids,
        "streaming_first_audio_faster_count": wins,
        "streaming_first_audio_not_faster_count": len(deltas) - wins,
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
    all_delta = report["matched_deltas"]["all_ok"]["first_audio_ready_ms_saved"]
    allowed_delta = report["matched_deltas"]["gate_allowed"]["first_audio_ready_ms_saved"]
    streaming_allowed = report["streaming"]["gate_allowed"]
    baseline_allowed = report["baseline"]["gate_allowed"]
    lines = [
        "# ShipVoice Server Real Streaming Comparison",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Baseline samples: {report['baseline']['num_samples']} ok / {report['baseline']['num_failed']} failed",
        f"- Streaming samples: {report['streaming']['num_samples']} ok / {report['streaming']['num_failed']} failed",
        f"- Gate-allowed matched samples: {report['matched_deltas']['gate_allowed']['matched_count']}",
        "",
        "## Gate-Allowed Latency",
        "",
        "| Metric | Baseline avg | Streaming avg | Streaming p50 | Streaming p90 | Streaming p95 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        (
            "| First audio ready ms | "
            f"{baseline_allowed['first_audio_ready_ms']['avg']} | "
            f"{streaming_allowed['first_audio_ready_ms']['avg']} | "
            f"{streaming_allowed['first_audio_ready_ms']['p50']} | "
            f"{streaming_allowed['first_audio_ready_ms']['p90']} | "
            f"{streaming_allowed['first_audio_ready_ms']['p95']} |"
        ),
        (
            "| LLM first delta ms | "
            f"{baseline_allowed['llm_first_delta_ms']['avg']} | "
            f"{streaming_allowed['llm_first_delta_ms']['avg']} | "
            f"{streaming_allowed['llm_first_delta_ms']['p50']} | "
            f"{streaming_allowed['llm_first_delta_ms']['p90']} | "
            f"{streaming_allowed['llm_first_delta_ms']['p95']} |"
        ),
        (
            "| Streamed audio segments | "
            f"{baseline_allowed['streamed_audio_segments']['avg']} | "
            f"{streaming_allowed['streamed_audio_segments']['avg']} | "
            f"{streaming_allowed['streamed_audio_segments']['p50']} | "
            f"{streaming_allowed['streamed_audio_segments']['p90']} | "
            f"{streaming_allowed['streamed_audio_segments']['p95']} |"
        ),
        "",
        "## First Audio Saved",
        "",
        f"- All ok samples avg saved: {all_delta['avg']} ms; p50 {all_delta['p50']} ms.",
        f"- Gate-allowed samples avg saved: {allowed_delta['avg']} ms; p50 {allowed_delta['p50']} ms.",
        (
            "- Gate-allowed faster count: "
            f"{report['matched_deltas']['gate_allowed']['streaming_first_audio_faster_count']} / "
            f"{report['matched_deltas']['gate_allowed']['matched_count']}."
        ),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare baseline and streaming real-chain batch outputs.")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--streaming", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=ROOT / "results" / "server_real_batch_comparison_20260623.json")
    parser.add_argument("--output-md", type=Path, default=ROOT / "results" / "server_real_batch_comparison_20260623.md")
    args = parser.parse_args()

    baseline_rows = load_jsonl(args.baseline)
    streaming_rows = load_jsonl(args.streaming)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_samples_path": str(args.baseline),
        "streaming_samples_path": str(args.streaming),
        "baseline": summarize_mode(baseline_rows, mode="baseline"),
        "streaming": summarize_mode(streaming_rows, mode="streaming"),
        "matched_deltas": {
            "all_ok": matched_deltas(baseline_rows, streaming_rows, gate_allowed_only=False),
            "gate_allowed": matched_deltas(baseline_rows, streaming_rows, gate_allowed_only=True),
        },
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
