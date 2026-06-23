from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "audio" / "audio_manifest.csv"
OUTPUT_CSV = ROOT / "data" / "audio" / "audio_manifest_a2_eval.csv"
OUTPUT_MD = ROOT / "docs" / "FIXED_AUDIO_COMMAND_SET_20260623.md"

DOMAIN_TERMS = [
    "密闭舱室",
    "有限空间",
    "动火",
    "舾装",
    "管路试压",
    "压载水舱",
    "吊装",
    "索具",
    "测氧测爆",
    "监护",
    "通风",
    "泄压",
    "消防",
    "脚手架",
    "临时用电",
    "叉车",
    "报警器",
    "法兰",
    "盲板",
]

BOUNDARY_SCENARIOS = {"off_domain", "unsafe", "prompt_injection", "refusal"}
COMPLEX_SCENARIOS = {"emergency", "authority", "reporting", "pressure_abnormal"}
TECHNICAL_SCENARIOS = {
    "confined_space",
    "pressure_test",
    "lifting",
    "hot_work",
    "ballast_tank",
    "scaffold",
    "signal",
    "welding",
    "electric",
    "gas_record",
    "watcher",
    "pressure",
    "grinding_ppe",
}


def read_rows() -> list[dict[str, str]]:
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def matched_terms(text: str) -> list[str]:
    return [term for term in DOMAIN_TERMS if term in text]


def classify(row: dict[str, str]) -> tuple[int, str, str, str, str]:
    scenario = row.get("scenario", "")
    noise = row.get("noise_condition", "")
    transcript = row.get("transcript", "")
    terms = matched_terms(transcript)

    if scenario in BOUNDARY_SCENARIOS:
        return (
            4,
            "安全边界与对抗输入",
            "验证 safety gate 是否短路危险、越界或提示注入输入，并确认不调用 LLM/TTS 正文链路。",
            "安全门控 / fail-closed",
            "gate-only 或 real-only streaming",
        )
    if noise != "quiet" or scenario in COMPLEX_SCENARIOS:
        return (
            3,
            "噪声、应急与复杂处置",
            "验证真实 ASR 在课堂或车间噪声下的稳定性，并检查系统对停工、上报、拒绝违章指令的处置质量。",
            "ASR 鲁棒性 / 应急处置",
            "real-only streaming",
        )
    if scenario in TECHNICAL_SCENARIOS or len(terms) >= 2:
        return (
            2,
            "船厂专有名词与专业作业",
            "验证船厂术语识别、术语后处理、RAG 检索、引用依据和 LLM 生成是否围绕真实作业风险展开。",
            "术语召回 / RAG 引用 / 回答质量",
            "baseline + streaming paired",
        )
    return (
        1,
        "基础安全问答",
        "验证系统对常见安全问句的基本理解、回答结构和可播放语音输出。",
        "基础链路连通性",
        "baseline + streaming paired",
    )


def build_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    enriched: list[dict[str, str]] = []
    for row in rows:
        level, label, focus, role, mode = classify(row)
        terms = matched_terms(row.get("transcript", ""))
        enriched.append(
            {
                **row,
                "difficulty_level": str(level),
                "difficulty_label": label,
                "evaluation_focus": focus,
                "domain_terms": "；".join(terms),
                "a2_role": role,
                "recommended_eval_mode": mode,
            }
        )
    return enriched


def write_csv(rows: list[dict[str, str]]) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict[str, str]]) -> str:
    lines = [
        "| ID | 场景 | 噪声 | 难度 | 指令文本 | 评测重点 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {id} | {scenario} | {noise_condition} | L{difficulty_level} {difficulty_label} | {transcript} | {a2_role} |".format(
                **row
            )
        )
    return "\n".join(lines)


def write_report(rows: list[dict[str, str]]) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    by_level = Counter(f"L{row['difficulty_level']} {row['difficulty_label']}" for row in rows)
    by_noise = Counter(row.get("noise_condition", "") for row in rows)
    by_scenario = Counter(row.get("scenario", "") for row in rows)
    term_rows = sum(1 for row in rows if row.get("domain_terms"))

    level_lines = "\n".join(f"- {key}: {value} 条" for key, value in sorted(by_level.items()))
    noise_lines = "\n".join(f"- {key}: {value} 条" for key, value in sorted(by_noise.items()))
    scenario_lines = "\n".join(f"- {key}: {value} 条" for key, value in sorted(by_scenario.items()))

    text = f"""# ShipVoice A2 固定音频指令集与难度梯度

生成时间: `{generated_at}`

本文件由 `scripts/build_a2_audio_eval_manifest.py` 从 `data/audio/audio_manifest.csv` 自动生成。原始 50 条录音清单不被覆盖；增强后的评测清单位于 `data/audio/audio_manifest_a2_eval.csv`。这样做的目的，是把 A2 题目要求中的“固定音频指令集、条数与难度梯度自定、建议包含专有名词与安全类问句”落实成可复现数据资产，而不是只在报告里口头说明。

## 1. 数据集定位

这 50 条录音来自三名组员实际录制的语音样本，覆盖文本安全问答、音频上传、浏览器录音和真实 ASR 转写链路所需的主要场景。它不是为了训练一个大规模端到端语音模型，而是用于 A2 级联式系统的固定评测集：同一批音频可以反复用于 ASR 术语识别、串行级联基线、流式改进链路、安全门控和等待体验对比。

## 2. 难度分层

{level_lines}

分层规则采用可解释策略：危险、越界和提示注入优先归入 L4；带课堂或车间噪声、应急和上报压力的样本归入 L3；包含船厂专有名词或专业作业流程的样本归入 L2；剩余常规安全问答归入 L1。当前共有 {term_rows} 条样本显式包含船厂安全术语，可用于检验 ASR 术语后处理和 RAG/LLM 的专业表达。

## 3. 噪声覆盖

{noise_lines}

噪声条件不是装饰字段。`quiet` 样本用于比较基础链路；`classroom` 和 `workshop_like` 样本用于检查真实 ASR 在答辩教室、车间背景噪声或远场录音下是否仍能稳定识别关键术语。

## 4. 场景覆盖

{scenario_lines}

这些场景覆盖有限空间、动火、吊装、试压、消防、临电、叉车、上报、拒绝违章要求、越界问题和提示注入。对于课程 A2 来说，这比单纯准备几条普通问句更有说服力，因为它同时检验了“听得准、答得对、该拒绝时拒绝、能解释依据”四个目标。

## 5. 全量固定指令表

{markdown_table(rows)}

## 6. 复现实验用法

1. ASR 术语评测使用原始清单：`python scripts/evaluate_asr_transcripts.py`
2. 难度清单生成使用本脚本：`python scripts/build_a2_audio_eval_manifest.py`
3. 串行基线和流式改进对比使用同一批样本，保证 baseline 与 improved 的输入一致。
4. 安全边界样本可以先用 gate-only 跑低成本检查，再接入 real-only 链路验证 fail-closed 行为。
"""
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text(text, encoding="utf-8")


def main() -> None:
    rows = read_rows()
    if not rows:
        raise SystemExit(f"no rows found in {SOURCE}")
    enriched = build_rows(rows)
    write_csv(enriched)
    write_report(enriched)
    print(f"wrote {OUTPUT_CSV}")
    print(f"wrote {OUTPUT_MD}")
    print(f"rows={len(enriched)} levels={dict(Counter(row['difficulty_level'] for row in enriched))}")


if __name__ == "__main__":
    main()
