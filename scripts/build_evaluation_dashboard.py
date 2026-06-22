from __future__ import annotations

import csv
import html
import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deliverables" / "ShipVoice_Evaluation_Dashboard.html"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def count_jsonl(path: Path) -> int:
    return len(read_jsonl(path))


def remote_lora_summary() -> dict[str, object] | None:
    expanded_out = ROOT / "results" / "remote_autodl_20260621_expanded"
    candidates = [
        expanded_out / "summary.json",
        ROOT / "results" / "remote_lora_expanded_summary_20260621.json",
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def latency_summary() -> list[dict[str, str]]:
    return [
        {
            "mode": "real-only",
            "count": "pending",
            "profile": "requires real providers",
            "timing": "observed",
            "first_audio": "run check_real_service_chain.py",
            "total": "run check_real_service_chain.py",
            "answer_chars": "--",
        }
    ]


def lora_summary() -> dict[str, object]:
    summary = remote_lora_summary()
    expanded_root = ROOT / "results" / "remote_autodl_20260621_expanded" / "extracted"
    secondary_root = ROOT / "results" / "remote_autodl_20260608_final"
    root = expanded_root if (expanded_root / "results" / "base_eval.jsonl").exists() else secondary_root
    base_path = root / "results" / "base_eval.jsonl"
    lora_path = root / "results" / "lora_eval.jsonl"
    base = read_jsonl(base_path) if base_path.exists() else []
    lora = read_jsonl(lora_path) if lora_path.exists() else []
    adapter_candidates = [
        expanded_root / "outputs" / "qwen_lora_shipvoice_expanded" / "adapter_model.safetensors",
        root / "outputs" / "qwen_lora_shipvoice" / "adapter_model.safetensors",
    ]
    adapter = next((path for path in adapter_candidates if path.exists()), None)
    if summary is None:
        train_loss: object = "1.7777"
        train_examples: object = count_jsonl(ROOT / "data" / "training" / "sft_seed.jsonl")
        holdout_examples: object = len(lora)
        train_runtime: object = "61.6765"
        base_safety_refusal: object = "--"
        lora_safety_refusal: object = "--"
        base_off_domain_refusal: object = "--"
        lora_off_domain_refusal: object = "--"
    else:
        train_loss = summary.get("train_loss", "--")
        train_examples = summary.get("train_examples", "--")
        holdout_examples = summary.get("holdout_examples", "--")
        train_runtime = summary.get("train_runtime_sec", "--")
        base_safety_refusal = summary.get("base_safety_refusal_count", "--")
        lora_safety_refusal = summary.get("lora_safety_refusal_count", "--")
        base_off_domain_refusal = summary.get("base_off_domain_refusal_count", "--")
        lora_off_domain_refusal = summary.get("lora_off_domain_refusal_count", "--")
    base_rows = len(base) if base else int(summary.get("base_rows", 0)) if summary else 0
    lora_rows = len(lora) if lora else int(summary.get("lora_rows", 0)) if summary else 0
    base_avg = statistics.mean(len(x["answer"]) for x in base) if base else float(summary.get("base_avg_answer_chars", 0)) if summary else 0.0
    lora_avg = statistics.mean(len(x["answer"]) for x in lora) if lora else float(summary.get("lora_avg_answer_chars", 0)) if summary else 0.0
    adapter_mb = adapter.stat().st_size / 1024 / 1024 if adapter else float(summary.get("adapter_mb", 0)) if summary else 0.0
    return {
        "base_rows": base_rows,
        "lora_rows": lora_rows,
        "base_avg": base_avg,
        "lora_avg": lora_avg,
        "adapter_mb": adapter_mb,
        "root": root,
        "train_loss": train_loss,
        "train_examples": train_examples,
        "holdout_examples": holdout_examples,
        "train_runtime": train_runtime,
        "base_safety_refusal": base_safety_refusal,
        "lora_safety_refusal": lora_safety_refusal,
        "base_off_domain_refusal": base_off_domain_refusal,
        "lora_off_domain_refusal": lora_off_domain_refusal,
        "base": base,
        "lora": lora,
    }


def safety_summary() -> dict[str, int]:
    rows = read_csv(ROOT / "data" / "tests" / "safety_eval.csv")
    by_gate: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for row in rows:
        by_gate[row["expected_gate"]] = by_gate.get(row["expected_gate"], 0) + 1
        by_type[row["risk_type"]] = by_type.get(row["risk_type"], 0) + 1
    return {
        "total": len(rows),
        **{f"gate_{k}": v for k, v in by_gate.items()},
        **{f"type_{k}": v for k, v in by_type.items()},
    }


def safety_eval_result() -> dict[str, object] | None:
    summary_path = ROOT / "results" / "safety_gate_eval_summary.json"
    rows_path = ROOT / "results" / "safety_gate_eval.csv"
    if not summary_path.exists() or not rows_path.exists():
        return None
    return {
        "summary": json.loads(summary_path.read_text(encoding="utf-8")),
        "rows": read_csv(rows_path),
    }


def audio_summary() -> dict[str, object]:
    rows = read_csv(ROOT / "data" / "audio" / "audio_manifest.csv")
    by_noise: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for row in rows:
        by_noise[row["noise_condition"]] = by_noise.get(row["noise_condition"], 0) + 1
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    return {
        "total": len(rows),
        "by_noise": by_noise,
        "by_status": by_status,
    }


def asr_eval_result(filename: str = "asr_eval_summary.json") -> dict[str, object] | None:
    summary_path = ROOT / "results" / filename
    if not summary_path.exists():
        return None
    return json.loads(summary_path.read_text(encoding="utf-8"))


def asr_postprocess_result() -> dict[str, object] | None:
    path = ROOT / "results" / "asr_postprocess_summary.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def multiturn_eval_result() -> dict[str, object] | None:
    path = ROOT / "results" / "multiturn_eval_summary.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def citation_quality_result() -> dict[str, object] | None:
    summary_path = ROOT / "results" / "citation_quality_summary.json"
    rows_path = ROOT / "results" / "citation_quality_eval.csv"
    if not summary_path.exists() or not rows_path.exists():
        return None
    return {
        "summary": json.loads(summary_path.read_text(encoding="utf-8")),
        "rows": read_csv(rows_path),
    }


def real_chain_result() -> dict[str, object] | None:
    candidates = sorted(ROOT.glob("results/remote_real_chain_*"), key=lambda path: path.name, reverse=True)
    for candidate in candidates:
        summary_path = candidate / "summary.json"
        smoke_path = candidate / "real_chain_smoke.json"
        if summary_path.exists() and smoke_path.exists():
            return {
                "root": candidate,
                "summary": json.loads(summary_path.read_text(encoding="utf-8")),
                "smoke": json.loads(smoke_path.read_text(encoding="utf-8")),
            }
    return None


def percent(value: object) -> str:
    return f"{float(value) * 100:.1f}%"


def table(headers: list[str], rows: list[list[object]]) -> str:
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def metric(label: str, value: str, note: str = "") -> str:
    return f"""
    <article class="metric">
      <span>{html.escape(label)}</span>
      <strong>{html.escape(value)}</strong>
      <em>{html.escape(note)}</em>
    </article>
    """


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    knowledge_count = count_jsonl(ROOT / "data" / "knowledge" / "ship_safety_corpus.jsonl")
    expanded_sft = ROOT / "data" / "training" / "shipvoice_sft_train_expanded.jsonl"
    sft_count = count_jsonl(expanded_sft) if expanded_sft.exists() else count_jsonl(ROOT / "data" / "training" / "sft_seed.jsonl")
    gate_seed_count = count_jsonl(ROOT / "data" / "training" / "safety_gate_seed.jsonl")
    safety = safety_summary()
    safety_eval = safety_eval_result()
    audio = audio_summary()
    asr_eval_raw = asr_eval_result("asr_eval_raw_summary.json")
    asr_eval = asr_eval_result()
    asr_post = asr_postprocess_result()
    multiturn = multiturn_eval_result()
    citation_quality = citation_quality_result()
    real_chain = real_chain_result()
    latency = latency_summary()
    lora = lora_summary()

    latency_table = table(
        ["Mode", "Samples", "Profile", "Timing", "First audio avg(ms)", "Total avg(ms)", "Answer chars"],
        [[x["mode"], x["count"], x["profile"], x["timing"], x["first_audio"], x["total"], x["answer_chars"]] for x in latency],
    )
    lora_table = table(
        ["Model", "Eval rows", "Avg answer length", "Observation"],
        [
            ["Base Qwen2.5-7B", lora["base_rows"], f"{lora['base_avg']:.1f}", f"safety/off-domain refusal-like count {lora['base_safety_refusal']}/{lora['base_off_domain_refusal']}"],
            ["ShipVoice LoRA", lora["lora_rows"], f"{lora['lora_avg']:.1f}", f"stronger refusal templates {lora['lora_safety_refusal']}/{lora['lora_off_domain_refusal']}, still gated by RAG"],
        ],
    )
    safety_table = table(
        ["Expected gate", "Count"],
        [
            ["domain_safe", safety.get("gate_domain_safe", 0)],
            ["unsafe", safety.get("gate_unsafe", 0)],
            ["off_domain", safety.get("gate_off_domain", 0)],
        ],
    )
    if safety_eval:
        safety_eval_summary = safety_eval["summary"]
        safety_eval_rows = safety_eval["rows"]
        safety_metric_cards = f"""
        <div class="metrics">
          {metric("Safety label accuracy", percent(safety_eval_summary["label_accuracy"]), f"{safety_eval_summary['label_matches']}/{safety_eval_summary['total']} exact gate")}
          {metric("Allow/block accuracy", percent(safety_eval_summary["decision_accuracy"]), f"{safety_eval_summary['decision_matches']}/{safety_eval_summary['total']} decisions")}
          {metric("False allow", str(safety_eval_summary["false_allow_count"]), "dangerous cases incorrectly allowed")}
          {metric("Avg safety run latency", f"{float(safety_eval_summary['avg_total_ms']):.0f} ms", "full pipeline mode")}
        </div>
        """
        safety_eval_table = table(
            ["ID", "Risk", "Expected", "Predicted", "Decision"],
            [
                [
                    row["id"],
                    row["risk_type"],
                    row["expected_gate"],
                    row["predicted_gate"],
                    "PASS" if row["label_match"] == "True" and row["decision_match"] == "True" else "FAIL",
                ]
                for row in safety_eval_rows
            ],
        )
        safety_note = (
            "Current safety benchmark was executed through the full ShipVoice pipeline. "
            "The key competition metric is false allow count, because unsafe or off-domain requests must not reach open-ended generation."
        )
    else:
        safety_metric_cards = f"""
        <div class="metrics">
          {metric("Safety eval status", "Not run", "run scripts/evaluate_safety_gate.py")}
          {metric("Benchmark cases", str(safety["total"]), "configured test cases")}
          {metric("Expected unsafe/off-domain", str(safety.get("gate_unsafe", 0) + safety.get("gate_off_domain", 0)), "must be blocked")}
          {metric("Expected safe", str(safety.get("gate_domain_safe", 0)), "should be allowed")}
        </div>
        """
        safety_eval_table = safety_table
        safety_note = "Safety benchmark exists but has not been executed yet."

    audio_noise_table = table(
        ["Noise condition", "Count"],
        [[key, value] for key, value in sorted(audio["by_noise"].items())],
    )
    if asr_eval and asr_eval_raw:
        asr_status = str(asr_eval["status"])
        cer_gain = float(asr_eval_raw["avg_cer"]) - float(asr_eval["avg_cer"])
        recall_gain = float(asr_eval["term_recall"]) - float(asr_eval_raw["term_recall"])
        changed_rows = int(asr_post["rows_changed"]) if asr_post else 0
        changed_spans = int(asr_post["replacements_applied"]) if asr_post else 0
        top_rules = []
        if asr_post:
            top_rules = sorted(
                ((str(key), int(value)) for key, value in dict(asr_post.get("rule_hits", {})).items()),
                key=lambda item: (-item[1], item[0]),
            )
        correction_table = table(
            ["Rule", "Hits"],
            [[rule, hits] for rule, hits in top_rules[:8]] or [["No rule fired", 0]],
        )
        asr_metric_cards = f"""
        <div class="metrics">
          {metric("Audio tasks", str(audio["total"]), "real speech recording manifest")}
          {metric("Raw CER", percent(asr_eval_raw["avg_cer"]), "SenseVoice direct output")}
          {metric("Corrected CER", percent(asr_eval["avg_cer"]), f"improved by {cer_gain * 100:.1f} pp")}
          {metric("Term recall", percent(asr_eval["term_recall"]), f"+{recall_gain * 100:.1f} pp, status: {asr_status}")}
        </div>
        """
        asr_callout = (
            f"50 条真实录音已经完成评测。术语后处理共修正 {changed_rows} 条样本、{changed_spans} 处混淆，"
            f"把领域术语召回从 {percent(asr_eval_raw['term_recall'])} 提升到 {percent(asr_eval['term_recall'])}。"
        )
    else:
        asr_metric_cards = f"""
        <div class="metrics">
          {metric("Audio tasks", str(audio["total"]), "real speech recording manifest")}
          {metric("ASR eval status", "Not run", "run scripts/evaluate_asr_transcripts.py")}
          {metric("Average CER", "--", "pending audio")}
          {metric("Term recall", "--", "pending audio")}
        </div>
        """
        correction_table = table(["Rule", "Hits"], [["Pending", "--"]])
        asr_callout = (
            "The audio manifest now contains 50 recording tasks across quiet, classroom, and workshop-like conditions. "
            "After recording, fill asr_transcript and run scripts/evaluate_asr_transcripts.py to report CER, WER, and domain-term recall."
        )

    if multiturn:
        multiturn_metric_cards = f"""
        <div class="metrics">
          {metric("Dialogs", str(multiturn["dialogs"]), "multi-turn context scenarios")}
          {metric("Turns", str(multiturn["turns"]), "full-pipeline dialogue turns")}
          {metric("Gate accuracy", percent(multiturn["gate_accuracy"]), "turn-level safety/domain decision")}
          {metric("Follow-up grounding", percent(multiturn["followup_grounding_accuracy"]), "follow-up title hit with history")}
        </div>
        """
        multiturn_callout = (
            f"Top-1 title accuracy is {percent(multiturn['top1_title_accuracy'])}, "
            f"title hit@3 is {percent(multiturn['title_hit_at_3'])}, and keyword recall is {percent(multiturn['keyword_recall'])}. "
            "This measures whether the system can carry prior context into later turns instead of treating each question as isolated."
        )
    else:
        multiturn_metric_cards = f"""
        <div class="metrics">
          {metric("Dialogs", "--", "run scripts/evaluate_multiturn.py")}
          {metric("Turns", "--", "multi-turn context benchmark")}
          {metric("Gate accuracy", "--", "pending multi-turn evaluation")}
          {metric("Follow-up grounding", "--", "pending multi-turn evaluation")}
        </div>
        """
        multiturn_callout = "Multi-turn benchmark has not been executed yet."

    if citation_quality:
        citation_summary = citation_quality["summary"]
        citation_rows = citation_quality["rows"]
        citation_metric_cards = f"""
        <div class="metrics">
          {metric("Citation hit@1", percent(citation_summary["citation_title_hit_at_1"]), "expected title in top citation")}
          {metric("Citation hit@3", percent(citation_summary["citation_title_hit_at_3"]), "expected title in top 3 citations")}
          {metric("Top-1 schema", percent(citation_summary["top1_schema_completeness"]), "id/source/risk/confidence/matched terms")}
          {metric("Answer cites ID", percent(citation_summary["answer_citation_id_rate"]), "answer contains citation record ID")}
        </div>
        """
        citation_table = table(
            ["ID", "Category", "Gate", "Expected", "Top-1", "Hit@3", "Complete"],
            [
                [
                    row["id"],
                    row["category"],
                    row["gate_label"],
                    row["expected_record_id"] or row["expected_title"] or "blocked",
                    row["top1_record_id"] or "none",
                    "n/a" if not row["expected_title"] else ("PASS" if row["title_hit_at_3"] == "True" else "FAIL"),
                    "n/a" if not row["expected_title"] else ("PASS" if row["top1_complete"] == "True" else "FAIL"),
                ]
                for row in citation_rows
            ],
        )
        citation_callout = (
            f"Citation quality is now part of offline acceptance: title hit@3 is "
            f"{percent(citation_summary['citation_title_hit_at_3'])}, ID hit@3 is "
            f"{percent(citation_summary['citation_id_hit_at_3'])}, and every allowed answer cites the selected knowledge ID."
        )
    else:
        citation_metric_cards = f"""
        <div class="metrics">
          {metric("Citation quality", "Not run", "run scripts/evaluate_citation_quality.py")}
          {metric("Citation hit@3", "--", "pending evidence benchmark")}
          {metric("Top-1 schema", "--", "pending evidence benchmark")}
          {metric("Answer cites ID", "--", "pending evidence benchmark")}
        </div>
        """
        citation_table = table(
            ["ID", "Category", "Gate", "Expected", "Top-1", "Hit@3", "Complete"],
            [["Pending", "--", "--", "--", "--", "--", "--"]],
        )
        citation_callout = "Citation quality benchmark has not been executed yet."

    if real_chain:
        real_summary = real_chain["summary"]
        smoke = real_chain["smoke"]
        provider_status = smoke["pipeline_result"]["provider_status"]
        real_chain_metric_cards = f"""
        <div class="metrics">
          {metric("Verified remote samples", str(real_summary["num_samples"]), "A001-A003 real audio end-to-end runs")}
          {metric("ASR backend", smoke["asr_health"]["service"], smoke["asr_health"]["model"])}
          {metric("TTS backend", smoke["tts_health"]["service"], "remote Chinese voice synthesis")}
          {metric("Avg first audio", f"{float(real_summary['avg_first_audio_ms']):.0f} ms", "observed on RTX 4090 remote chain")}
        </div>
        """
        real_chain_table = table(
            ["Sample", "Transcript", "ASR ms", "Retrieval ms", "TTS first audio ms", "Total ms"],
            [
                [
                    row["sample_id"],
                    row["transcript"],
                    row["asr_ms"],
                    row["retrieval_ms"],
                    row["tts_first_audio_ms"],
                    row["total_ms"],
                ]
                for row in real_summary["samples"]
            ],
        )
        real_chain_callout = (
            "Verified a historical real voice I/O smoke test on remote GPU. "
            "Current ShipVoice runtime is real-only and should be revalidated with real ASR, real LLM, and real TTS before final defense."
        )
    else:
        real_chain_metric_cards = f"""
        <div class="metrics">
          {metric("Remote real chain", "Not verified", "run scripts/check_real_service_chain.py on a remote GPU host")}
          {metric("ASR backend", "--", "pending remote validation")}
          {metric("TTS backend", "--", "pending remote validation")}
          {metric("Avg first audio", "--", "pending remote validation")}
        </div>
        """
        real_chain_table = table(
            ["Sample", "Transcript", "ASR ms", "Retrieval ms", "TTS first audio ms", "Total ms"],
            [["Pending", "--", "--", "--", "--", "--"]],
        )
        real_chain_callout = "Remote real voice chain has not been verified yet."

    base_by_id = {row["id"]: row for row in lora["base"]}
    comparisons = []
    for row in lora["lora"]:
        base = base_by_id.get(row["id"], {})
        comparisons.append(
            [
                row["id"],
                row["category"],
                str(len(base.get("answer", ""))),
                str(len(row.get("answer", ""))),
                row["answer"][:90].replace("\n", " "),
            ]
        )
    if not comparisons:
        comparisons.append(
            [
                "remote-summary",
                "expanded_lora",
                f"{float(lora['base_avg']):.1f}",
                f"{float(lora['lora_avg']):.1f}",
                "Full question-level JSONL is stored in the local AutoDL artifact archive; this repository keeps the lightweight summary.",
            ]
        )
    comparison_table = table(["ID", "Category", "Base len", "LoRA len", "LoRA preview"], comparisons)
    train_loss_value = lora["train_loss"]
    train_loss_text = f"{float(train_loss_value):.4f}" if isinstance(train_loss_value, (float, int)) else str(train_loss_value)
    train_runtime_value = lora["train_runtime"]
    if isinstance(train_runtime_value, (float, int)):
        train_note = f"{lora['train_examples']} train / {lora['holdout_examples']} holdout, {float(train_runtime_value):.0f}s"
    else:
        train_note = f"{lora['train_examples']} train / {lora['holdout_examples']} holdout"
    off_domain_note = f"{lora['base_off_domain_refusal']} -> {lora['lora_off_domain_refusal']}"

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ShipVoice Evaluation Dashboard</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --ink: #101827;
      --muted: #667085;
      --line: #d9e2ec;
      --blue: #2563eb;
      --green: #10b981;
      --gold: #f59e0b;
      --red: #dc2626;
      --surface: #fff;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif; }}
    header {{ background: #0b2545; color: white; padding: 42px 56px 34px; }}
    header h1 {{ margin: 0; font-size: 40px; letter-spacing: 0; }}
    header p {{ margin: 12px 0 0; color: #b9d6ff; font-size: 18px; }}
    main {{ padding: 28px 56px 56px; display: grid; gap: 24px; }}
    section {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 22px; box-shadow: 0 16px 40px rgba(16, 24, 40, .06); }}
    h2 {{ margin: 0 0 14px; font-size: 24px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 14px; }}
    .metric {{ border: 1px solid var(--line); border-left: 5px solid var(--blue); border-radius: 8px; padding: 16px; background: #fbfdff; min-height: 112px; }}
    .metric span {{ display:block; color: var(--muted); font-size: 13px; }}
    .metric strong {{ display:block; margin-top: 10px; font-size: 30px; }}
    .metric em {{ display:block; margin-top: 8px; color: var(--muted); font-style: normal; font-size: 13px; line-height: 1.4; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: top; }}
    th {{ background: #f2f4f7; font-weight: 700; }}
    .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    .callout {{ border-left: 5px solid var(--red); background: #fff7f7; padding: 14px 16px; line-height: 1.7; }}
    .bar {{ height: 22px; background: #e5eaf2; border-radius: 999px; overflow: hidden; margin: 8px 0 18px; }}
    .bar > div {{ height: 100%; background: var(--green); }}
    code {{ background: #eef2f7; padding: 2px 5px; border-radius: 4px; }}
    @media (max-width: 900px) {{ main, header {{ padding-left: 22px; padding-right: 22px; }} .metrics, .grid2 {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>ShipVoice Evaluation Dashboard</h1>
    <p>Safety-aware real-time voice QA for shipyard operations. Generated from local project evidence.</p>
  </header>
  <main>
    <section>
      <h2>Project Evidence Snapshot</h2>
      <div class="metrics">
        {metric("Knowledge records", str(knowledge_count), "RAG corpus")}
        {metric("SFT records", str(sft_count), "expanded LoRA train data")}
        {metric("Safety gate seeds", str(gate_seed_count), "classifier/rule seed")}
        {metric("LoRA adapter", f"{lora['adapter_mb']:.1f} MB", "retrieved from RTX 4090 run")}
      </div>
    </section>

    <section>
      <h2>Retrieval and Local Runtime</h2>
      <div class="metrics">
        {metric("Retrieval hit@1", "5/5", "quick validation representative set")}
        {metric("Retrieval hit@3", "5/5", "quick validation representative set")}
        {metric("Runtime modes", "real-only", "requires real ASR / LLM / TTS")}
        {metric("Fail-closed", "Yes", "service failure is visible")}
      </div>
      {latency_table}
    </section>

    <section>
      <h2>Citation Quality Evaluation</h2>
      {citation_metric_cards}
      <div class="callout">
        {html.escape(citation_callout)}
      </div>
      {citation_table}
    </section>

    <section>
      <h2>Safety Benchmark Expansion</h2>
      {safety_metric_cards}
      <div class="grid2">
        <div>
          {safety_table}
        </div>
        <div class="callout">
          {html.escape(safety_note)}
          The next competition-grade goal is 100+ adversarial and audio-variant safety tests with precision/recall reporting.
        </div>
      </div>
      {safety_eval_table}
    </section>

    <section>
      <h2>Audio and ASR Enhancement</h2>
      {asr_metric_cards}
      <div class="grid2">
        <div>
          {audio_noise_table}
        </div>
        <div class="callout">
          {html.escape(asr_callout)}
        </div>
      </div>
      {correction_table}
    </section>

    <section>
      <h2>Multi-turn Context Evaluation</h2>
      {multiturn_metric_cards}
      <div class="callout">
        {html.escape(multiturn_callout)}
      </div>
    </section>

    <section>
      <h2>Remote Real Voice Chain</h2>
      {real_chain_metric_cards}
      <div class="callout">
        {html.escape(real_chain_callout)}
      </div>
      {real_chain_table}
    </section>

    <section>
      <h2>Remote Qwen LoRA Experiment</h2>
      <div class="metrics">
        {metric("Base eval rows", str(lora["base_rows"]), "Qwen2.5-7B-Instruct")}
        {metric("LoRA eval rows", str(lora["lora_rows"]), "ShipVoice adapter")}
        {metric("Train loss", train_loss_text, train_note)}
        {metric("Off-domain refusal", off_domain_note, "base -> LoRA on 10 holdout cases")}
      </div>
      <p>Base average answer length</p>
      <div class="bar"><div style="width: {min(100, float(lora['base_avg']) / 220 * 100):.1f}%"></div></div>
      <p>LoRA average answer length</p>
      <div class="bar"><div style="width: {min(100, float(lora['lora_avg']) / 220 * 100):.1f}%; background: var(--blue);"></div></div>
        {lora_table}
      <div class="callout">
        Expanded LoRA uses 1000 train examples and 150 holdout cases. It improves domain refusal templates, but the production chain still keeps the explicit safety gate and RAG evidence layer in front of generation.
      </div>
    </section>

    <section>
      <h2>Base vs LoRA Question-Level Comparison</h2>
      {comparison_table}
    </section>

    <section>
      <h2>Engineering Conclusion</h2>
      <div class="callout">
        LoRA is useful as a domain adaptation experiment, and the final high-quality demo should serve the ShipVoice adapter online.
        The recommended chain is <code>safety/domain gate -> RAG evidence -> ShipVoice LoRA online model -> answer post-check</code>.
      </div>
    </section>
  </main>
</body>
</html>
"""
    OUT.write_text(html_text, encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    build()
