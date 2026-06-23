from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPEATED_SUMMARY = ROOT / "results" / "server_real_repeated_20260623" / "summary.json"
REPEATED_SAMPLES = ROOT / "results" / "server_real_repeated_20260623" / "samples.jsonl"
BROWSER_ONPLAYING = ROOT / "results" / "browser_onplaying_streamable_20260623.json"
OUTPUT_DIR = ROOT / "results" / "waiting_experience_20260623"
PAIR_CSV = OUTPUT_DIR / "proxy_wait_pairs.csv"
BROWSER_CSV = OUTPUT_DIR / "browser_streaming_wait_scores.csv"
SUMMARY_JSON = OUTPUT_DIR / "summary.json"
REPORT_MD = OUTPUT_DIR / "report.md"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def wait_score(ms: float | int | None) -> tuple[int, str]:
    if ms is None:
        return 0, "无可评分延迟"
    value = float(ms)
    if value <= 2500:
        return 5, "几乎即时"
    if value <= 4000:
        return 4, "等待可接受"
    if value <= 6000:
        return 3, "有等待感但可接受"
    if value <= 9000:
        return 2, "等待明显"
    return 1, "等待过长"


def first_audio_ms(row: dict[str, Any]) -> int | None:
    for key in ("server_first_audio_chunk_ready_ms", "server_audio_payload_ready_ms", "first_audio_ms"):
        value = row.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(round(value))
    return None


def pct(saved_ms: int | None, baseline_ms: int | None) -> float | None:
    if saved_ms is None or not baseline_ms:
        return None
    return round(saved_ms / baseline_ms * 100, 2)


def avg(values: list[float | int]) -> float | None:
    if not values:
        return None
    return round(float(mean(values)), 2)


def quantile(values: list[float | int], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def aggregate(values: list[float | int]) -> dict[str, Any]:
    return {
        "count": len(values),
        "avg": avg(values),
        "p50": quantile(values, 0.5),
        "p90": quantile(values, 0.9),
        "p95": quantile(values, 0.95),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def build_pair_rows(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_pair: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in samples:
        if row.get("status") != "ok" or not row.get("gate_allowed"):
            continue
        repeat = str(row.get("repeat", ""))
        sample_id = str(row.get("sample_id", ""))
        mode = str(row.get("mode", ""))
        if repeat and sample_id and mode in {"baseline", "streaming"}:
            by_pair[(repeat, sample_id)][mode] = row

    pair_rows: list[dict[str, Any]] = []
    for (repeat, sample_id), modes in sorted(by_pair.items(), key=lambda item: (int(item[0][0]), item[0][1])):
        baseline = modes.get("baseline")
        streaming = modes.get("streaming")
        if not baseline or not streaming:
            continue
        baseline_ms = first_audio_ms(baseline)
        streaming_ms = first_audio_ms(streaming)
        saved_ms = baseline_ms - streaming_ms if baseline_ms is not None and streaming_ms is not None else None
        baseline_score, baseline_label = wait_score(baseline_ms)
        streaming_score, streaming_label = wait_score(streaming_ms)
        pair_rows.append(
            {
                "pair_id": f"r{repeat}:{sample_id}",
                "repeat": repeat,
                "sample_id": sample_id,
                "reference_transcript": baseline.get("reference_transcript", ""),
                "baseline_first_audio_ms": baseline_ms,
                "streaming_first_audio_ms": streaming_ms,
                "saved_ms": saved_ms,
                "saved_percent": pct(saved_ms, baseline_ms),
                "baseline_wait_score_1_5": baseline_score,
                "baseline_wait_label": baseline_label,
                "streaming_wait_score_1_5": streaming_score,
                "streaming_wait_label": streaming_label,
                "streamed_audio_segments": streaming.get("streamed_audio_segments", 0),
                "streaming_response_mode": streaming.get("response_mode", ""),
            }
        )
    return pair_rows


def build_browser_rows(browser: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in browser.get("rows", []):
        onplaying = row.get("client_audio_onplaying_ms")
        score, label = wait_score(onplaying)
        rows.append(
            {
                "sample_id": row.get("sample_id", ""),
                "audio_name": row.get("audio_name", ""),
                "transcript_reference": row.get("transcript_reference", ""),
                "client_audio_onplaying_ms": onplaying,
                "first_audio_chunk_arrival_ms": row.get("first_audio_chunk_arrival_ms"),
                "server_first_audio_chunk_ready_ms": row.get("server_first_audio_chunk_ready_ms"),
                "result_arrival_ms": row.get("result_arrival_ms"),
                "audio_chunks": row.get("audio_chunks"),
                "play_error": row.get("play_error", ""),
                "wait_score_1_5": score,
                "wait_label": label,
                "response_mode": row.get("response_mode", ""),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_summary(pair_rows: list[dict[str, Any]], browser_rows: list[dict[str, Any]], repeated: dict[str, Any]) -> dict[str, Any]:
    baseline_ms = [row["baseline_first_audio_ms"] for row in pair_rows if row["baseline_first_audio_ms"] is not None]
    streaming_ms = [row["streaming_first_audio_ms"] for row in pair_rows if row["streaming_first_audio_ms"] is not None]
    saved_ms = [row["saved_ms"] for row in pair_rows if row["saved_ms"] is not None]
    baseline_scores = [row["baseline_wait_score_1_5"] for row in pair_rows if row["baseline_wait_score_1_5"]]
    streaming_scores = [row["streaming_wait_score_1_5"] for row in pair_rows if row["streaming_wait_score_1_5"]]
    browser_onplaying = [
        row["client_audio_onplaying_ms"]
        for row in browser_rows
        if isinstance(row.get("client_audio_onplaying_ms"), (int, float))
    ]
    browser_scores = [row["wait_score_1_5"] for row in browser_rows if row["wait_score_1_5"]]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "Automated proxy subjective waiting score from real timing logs; it does not claim to be a human Likert survey.",
        "inputs": {
            "repeated_summary": str(REPEATED_SUMMARY.relative_to(ROOT)),
            "repeated_samples": str(REPEATED_SAMPLES.relative_to(ROOT)),
            "browser_onplaying": str(BROWSER_ONPLAYING.relative_to(ROOT)),
        },
        "real_chain_repeated": {
            "num_pair_rows": len(pair_rows),
            "baseline_first_audio_ms": aggregate(baseline_ms),
            "streaming_first_audio_ms": aggregate(streaming_ms),
            "first_audio_saved_ms": aggregate(saved_ms),
            "baseline_wait_score_1_5_avg": avg(baseline_scores),
            "streaming_wait_score_1_5_avg": avg(streaming_scores),
            "streaming_faster_count": sum(1 for value in saved_ms if value > 0),
            "streaming_not_faster_count": sum(1 for value in saved_ms if value <= 0),
            "source_gate_allowed_pairs": repeated.get("paired_deltas", {}).get("gate_allowed", {}),
        },
        "browser_streaming_onplaying": {
            "num_rows": len(browser_rows),
            "num_ok": sum(1 for row in browser_rows if not row.get("play_error")),
            "client_audio_onplaying_ms": aggregate(browser_onplaying),
            "wait_score_1_5_avg": avg(browser_scores),
        },
        "score_rubric": {
            "5": "<= 2500 ms, 几乎即时",
            "4": "<= 4000 ms, 等待可接受",
            "3": "<= 6000 ms, 有等待感但可接受",
            "2": "<= 9000 ms, 等待明显",
            "1": "> 9000 ms, 等待过长",
        },
    }


def write_report(summary: dict[str, Any]) -> None:
    repeated = summary["real_chain_repeated"]
    browser = summary["browser_streaming_onplaying"]
    source_pairs = repeated["source_gate_allowed_pairs"]
    saved = repeated["first_audio_saved_ms"]

    text = f"""# ShipVoice 主观等待体验代理评分报告

生成时间: `{summary['generated_at']}`

## 1. 口径说明

本报告补齐课程 A2 要求中的“主观等待体验可量化对比”。由于本轮没有重新组织真人问卷，报告没有伪造真人主观数据，而是采用自动化代理评分：把真实链路记录到的首段可播放延迟映射到 1-5 分等待体验等级。该结果可以用于答辩和报告中的工程量化说明；如果后续要做真人用户研究，可以直接沿用同一评分表替换为人工打分。

评分规则如下：

| 分数 | 延迟区间 | 体验解释 |
| --- | --- | --- |
| 5 | <= 2500 ms | 几乎即时 |
| 4 | <= 4000 ms | 等待可接受 |
| 3 | <= 6000 ms | 有等待感但可接受 |
| 2 | <= 9000 ms | 等待明显 |
| 1 | > 9000 ms | 等待过长 |

## 2. 基线 vs 流式改进

输入数据来自 `results/server_real_repeated_20260623/samples.jsonl` 和对应 summary。仅统计安全门控放行、需要进入 LLM/TTS 正文链路的样本，避免把短路拒答样本混入低延迟收益计算。

| 指标 | 串行基线 | 流式改进 |
| --- | ---: | ---: |
| 配对样本数 | {repeated['num_pair_rows']} | {repeated['num_pair_rows']} |
| 首段可播放延迟均值 | {repeated['baseline_first_audio_ms']['avg']} ms | {repeated['streaming_first_audio_ms']['avg']} ms |
| 首段可播放延迟 P50 | {repeated['baseline_first_audio_ms']['p50']} ms | {repeated['streaming_first_audio_ms']['p50']} ms |
| 首段可播放延迟 P90 | {repeated['baseline_first_audio_ms']['p90']} ms | {repeated['streaming_first_audio_ms']['p90']} ms |
| 代理等待评分均值 | {repeated['baseline_wait_score_1_5_avg']} / 5 | {repeated['streaming_wait_score_1_5_avg']} / 5 |

在 {source_pairs.get('matched_count', repeated['num_pair_rows'])} 个 gate-allowed 配对样本中，流式改进首段音频更快的次数为 {source_pairs.get('streaming_first_audio_faster_count', repeated['streaming_faster_count'])}，未更快次数为 {source_pairs.get('streaming_first_audio_not_faster_count', repeated['streaming_not_faster_count'])}。平均节省 {saved['avg']} ms，P50 节省 {saved['p50']} ms，P90 节省 {saved['p90']} ms。

## 3. 浏览器端真实播放观测

输入数据来自 `results/browser_onplaying_streamable_20260623.json`。该结果不是服务端 ready 时间，而是浏览器 `audio.onplaying` 事件触发时间，更接近答辩现场用户实际感受到的“音频开始播放”。

| 指标 | 浏览器流式播放 |
| --- | ---: |
| 样本数 | {browser['num_rows']} |
| 播放成功数 | {browser['num_ok']} |
| `audio.onplaying` 均值 | {browser['client_audio_onplaying_ms']['avg']} ms |
| `audio.onplaying` P50 | {browser['client_audio_onplaying_ms']['p50']} ms |
| `audio.onplaying` P90 | {browser['client_audio_onplaying_ms']['p90']} ms |
| 代理等待评分均值 | {browser['wait_score_1_5_avg']} / 5 |

## 4. 结论

串行基线需要等完整 LLM 输出和完整 TTS 合成后才能播放，因此用户等待感明显。流式改进把 LLM token 流、句级切分和 TTS 分段播放结合起来，使首段音频可以先播放，虽然完整回答仍需要继续生成，但用户已经能更早听到系统反馈。这个结果正好对应 A2 题目的低延迟要求：优化目标不是只压缩总耗时，而是降低“用户停止说话/提交问题后到首段音频可播放”的等待时间。

## 5. 产物

- 配对样本评分: `results/waiting_experience_20260623/proxy_wait_pairs.csv`
- 浏览器播放评分: `results/waiting_experience_20260623/browser_streaming_wait_scores.csv`
- 机器可读摘要: `results/waiting_experience_20260623/summary.json`
"""
    REPORT_MD.write_text(text, encoding="utf-8")


def main() -> None:
    repeated = load_json(REPEATED_SUMMARY)
    samples = load_jsonl(REPEATED_SAMPLES)
    browser = load_json(BROWSER_ONPLAYING)
    pair_rows = build_pair_rows(samples)
    browser_rows = build_browser_rows(browser)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(PAIR_CSV, pair_rows)
    write_csv(BROWSER_CSV, browser_rows)
    summary = build_summary(pair_rows, browser_rows, repeated)
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(summary)
    print(f"wrote {PAIR_CSV}")
    print(f"wrote {BROWSER_CSV}")
    print(f"wrote {SUMMARY_JSON}")
    print(f"wrote {REPORT_MD}")
    print(
        "pairs={pairs} browser_rows={browser_rows} streaming_score={score}".format(
            pairs=len(pair_rows),
            browser_rows=len(browser_rows),
            score=summary["real_chain_repeated"]["streaming_wait_score_1_5_avg"],
        )
    )


if __name__ == "__main__":
    main()
