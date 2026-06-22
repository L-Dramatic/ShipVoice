from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
REPORT_JSON = RESULTS_DIR / "project_acceptance_report.json"
REPORT_MD = RESULTS_DIR / "project_acceptance_report.md"
REAL_CHAIN_JSON = RESULTS_DIR / "real_chain_smoke.json"
LORA_SUMMARY_JSON = RESULTS_DIR / "remote_autodl_20260621_expanded" / "summary.json"
DIRTY_STATUS_IGNORE_PREFIXES = ("logs/",)
DIRTY_STATUS_IGNORE_PATHS = {
    "configs/runtime.real.env",
    "results/project_acceptance_report.json",
    "results/project_acceptance_report.md",
    "results/real_chain_smoke.json",
}


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def git_value(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return completed.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def git_status_porcelain() -> str:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return completed.stdout.rstrip("\n")
    except (OSError, subprocess.CalledProcessError):
        return ""


def normalized_status_path(line: str) -> str:
    path = line[3:].strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1].strip()
    return path.replace("\\", "/").strip('"')


def source_tree_dirty() -> bool:
    raw_status = git_status_porcelain()
    for line in raw_status.splitlines():
        path = normalized_status_path(line)
        if path in DIRTY_STATUS_IGNORE_PATHS:
            continue
        if any(path.startswith(prefix) for prefix in DIRTY_STATUS_IGNORE_PREFIXES):
            continue
        return True
    return False


def current_lora_chain_status(real_chain: dict[str, Any]) -> tuple[bool, str]:
    if not real_chain:
        return False, "尚未生成 results/real_chain_smoke.json。"
    llm_health = real_chain.get("llm_health", {})
    models = llm_health.get("models", []) if isinstance(llm_health, dict) else []
    health = llm_health.get("health", {}) if isinstance(llm_health, dict) else {}
    provider_status = real_chain.get("pipeline_result", {}).get("provider_status", {})
    model_ok = any("shipvoice" in str(model_id).lower() for model_id in models)
    adapter_ok = isinstance(health, dict) and health.get("adapter_loaded") is True
    required = real_chain.get("llm_require_lora") is True
    provider_ok = "shipvoice" in str(provider_status.get("llm", "")).lower()
    if model_ok and adapter_ok and required and provider_ok:
        return True, "当前 real_chain_smoke 已确认 ShipVoice LoRA adapter 在线加载。"
    return False, "当前 real_chain_smoke 不是 ShipVoice LoRA adapter 在线链路证据，需要重新验收。"


def file_status(path: str) -> dict[str, Any]:
    target = ROOT / path
    return {
        "path": path,
        "exists": target.exists(),
        "bytes": target.stat().st_size if target.exists() else 0,
    }


def pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def ms(value: Any) -> str:
    try:
        return f"{float(value):.0f} ms"
    except (TypeError, ValueError):
        return "n/a"


def build_report() -> dict[str, Any]:
    safety = read_json(RESULTS_DIR / "safety_gate_eval_summary.json", {})
    multiturn = read_json(RESULTS_DIR / "multiturn_eval_summary.json", {})
    citation = read_json(RESULTS_DIR / "citation_quality_summary.json", {})
    asr = read_json(RESULTS_DIR / "asr_eval_summary.json", {})
    real_chain = read_json(REAL_CHAIN_JSON, {})
    lora_summary = read_json(LORA_SUMMARY_JSON, {})
    lora_chain_verified, lora_chain_reason = current_lora_chain_status(real_chain)
    knowledge_count = count_jsonl(ROOT / "data" / "knowledge" / "ship_safety_corpus.jsonl")
    training_sft_count = count_jsonl(ROOT / "data" / "training" / "sft_seed.jsonl")
    safety_seed_count = count_jsonl(ROOT / "data" / "training" / "safety_gate_seed.jsonl")

    capabilities = [
        {
            "name": "用户端语音/文本问答",
            "status": "implemented",
            "evidence": ["web/static/index.html", "src/shipvoice/fastapi_app.py"],
            "notes": "支持文本输入、音频上传、浏览器直接录音、TTS 播放。",
        },
        {
            "name": "ASR -> 安全门控 -> RAG -> LLM -> TTS 主链路",
            "status": "implemented",
            "evidence": ["src/shipvoice/pipeline.py", "src/shipvoice/providers.py"],
            "notes": "采用真实 provider 与 fail-closed 策略；ASR、LLM、TTS 服务缺失时请求失败并记录错误。",
        },
        {
            "name": "ShipVoice LoRA 在线推理服务",
            "status": "implemented",
            "evidence": ["remote/serve_transformers_openai.py", "remote/start_lora_llm.sh", "remote/stop_lora_llm.sh"],
            "notes": "远端服务可强制加载 LoRA adapter；adapter 不存在或未加载时启动失败。",
        },
        {
            "name": "管理后台与审计",
            "status": "implemented",
            "evidence": ["web/static/admin.html", "src/shipvoice/sqlite_store.py", "tests/test_admin_api.py"],
            "notes": "知识库治理、运行记录、case ledger、评测任务、导出能力已接入。",
        },
        {
            "name": "领域知识库与 RAG",
            "status": "implemented",
            "evidence": ["data/knowledge/ship_safety_corpus.jsonl", "data/knowledge/ship_safety_index.json"],
            "notes": f"当前知识条目 {knowledge_count} 条；回答侧返回知识 ID、来源、风险级别、匹配词和置信度。",
        },
        {
            "name": "安全评测闭环",
            "status": "implemented",
            "evidence": ["data/tests/safety_eval.csv", "results/safety_gate_eval_summary.json"],
            "notes": f"{safety.get('total', 0)} 条安全样本，决策准确率 {pct(safety.get('decision_accuracy'))}。",
        },
        {
            "name": "可解释证据引用",
            "status": "implemented",
            "evidence": [
                "src/shipvoice/providers.py",
                "web/static/app.js",
                "scripts/evaluate_citation_quality.py",
                "results/citation_quality_summary.json",
                "tests/test_evidence_citations.py",
            ],
            "notes": (
                "前端证据卡片展示 citation ID、source、risk、confidence、tags 和 matched terms；"
                "当前结构测试已覆盖证据字段。"
                if not lora_chain_verified
                else (
                    f"当前 LoRA 链路 citation title hit@3 {pct(citation.get('citation_title_hit_at_3'))}，"
                    f"Top-1 schema 完整率 {pct(citation.get('top1_schema_completeness'))}。"
                )
            ),
        },
        {
            "name": "当前真实语音链路验收",
            "status": "verified_lora_chain" if lora_chain_verified else "pending_lora_chain_validation",
            "evidence": ["scripts/check_real_service_chain.py", "results/real_chain_smoke.json"],
            "notes": lora_chain_reason,
        },
        {
            "name": "微调与安全数据资产",
            "status": "completed_experiment",
            "evidence": ["data/training/shipvoice_sft_train_expanded.jsonl", "remote/train_qwen_lora.py", "results/remote_autodl_20260621_expanded/summary.json"],
            "notes": (
                f"扩展 SFT {lora_summary.get('train_examples', 0)} 条，holdout {lora_summary.get('holdout_examples', 0)} 条；"
                f"LoRA train loss {lora_summary.get('train_loss', 'n/a')}，adapter 约 {lora_summary.get('adapter_mb', 0)} MB。"
            ),
        },
        {
            "name": "容器化与远程部署",
            "status": "implemented",
            "evidence": ["Dockerfile", "docker-compose.app.yml", "remote/start_shipvoice_real_services.sh"],
            "notes": "支持本地 FastAPI 应用、Docker 运行、AutoDL 真实模型服务脚本。",
        },
    ]

    metrics = {
        "safety_gate": {
            "total": safety.get("total", 0),
            "decision_accuracy": safety.get("decision_accuracy"),
            "false_allow_count": safety.get("false_allow_count"),
            "false_block_count": safety.get("false_block_count"),
        },
        "multiturn": {
            "dialogs": multiturn.get("dialogs", 0),
            "turns": multiturn.get("turns", 0),
            "followup_grounding_accuracy": multiturn.get("followup_grounding_accuracy"),
            "keyword_recall": multiturn.get("keyword_recall"),
        },
        "citation_quality": {
            "total": citation.get("total", 0),
            "allowed_cases": citation.get("allowed_cases", 0),
            "gate_allowed_accuracy": citation.get("gate_allowed_accuracy"),
            "citation_title_hit_at_1": citation.get("citation_title_hit_at_1"),
            "citation_title_hit_at_3": citation.get("citation_title_hit_at_3"),
            "citation_id_hit_at_3": citation.get("citation_id_hit_at_3"),
            "top1_schema_completeness": citation.get("top1_schema_completeness"),
            "citation_schema_completeness": citation.get("citation_schema_completeness"),
            "answer_citation_id_rate": citation.get("answer_citation_id_rate"),
        },
        "asr_manifest": {
            "evaluated_rows": asr.get("evaluated_rows", 0),
            "missing_audio_rows": asr.get("missing_audio_rows", 0),
            "term_recall": asr.get("term_recall"),
            "status": asr.get("status", "unknown"),
        },
        "real_chain_smoke": {
            "verified_lora_chain": lora_chain_verified,
            "reason": lora_chain_reason,
            "sample_id": real_chain.get("sample_id", ""),
            "asr_ms": real_chain.get("pipeline_result", {}).get("metrics", {}).get("asr_ms"),
            "retrieval_ms": real_chain.get("pipeline_result", {}).get("metrics", {}).get("retrieval_ms"),
            "llm_first_token_ms": real_chain.get("pipeline_result", {}).get("metrics", {}).get("llm_first_token_ms"),
            "tts_first_audio_ms": real_chain.get("pipeline_result", {}).get("metrics", {}).get("tts_first_audio_ms"),
            "first_audio_ms": real_chain.get("pipeline_result", {}).get("metrics", {}).get("first_audio_ms"),
        },
        "lora_experiment": {
            "train_examples": lora_summary.get("train_examples", 0),
            "holdout_examples": lora_summary.get("holdout_examples", 0),
            "base_rows": lora_summary.get("base_rows", 0),
            "lora_rows": lora_summary.get("lora_rows", 0),
            "train_loss": lora_summary.get("train_loss"),
            "adapter_mb": lora_summary.get("adapter_mb"),
            "base_off_domain_refusal_count": lora_summary.get("base_off_domain_refusal_count"),
            "lora_off_domain_refusal_count": lora_summary.get("lora_off_domain_refusal_count"),
        },
    }

    artifacts = [
        file_status("README.md"),
        file_status("docs/PHASE1_SCORECARD.md"),
        file_status("docs/OPERATIONS_RUNBOOK.md"),
        file_status("docs/ARCHITECTURE.md"),
        file_status("results/citation_quality_report.md"),
        file_status("results/citation_quality_summary.json"),
        file_status("results/citation_quality_eval.csv"),
        file_status("deliverables/ShipVoice_Evaluation_Dashboard.html"),
        file_status("deliverables/ShipVoice_Final_Defense_Deck_Draft.pptx"),
        file_status("deliverables/ShipVoice_船厂安全实时语音问答助手_项目报告_比赛增强版.docx"),
        file_status("web/static/index.html"),
        file_status("web/static/admin.html"),
        file_status("Dockerfile"),
    ]

    limitations = [
        "当前本地证据必须重新跑 ShipVoice LoRA 在线链路验收，不能再使用旧基座模型结果代表最终系统。",
        "真实端到端语音链路尚未扩展到 30+ 条真实端到端压测。",
        "TTS 首音延迟仍需优化，答辩时应如实说明瓶颈在 TTS 服务。",
        "当前 real-only 版本依赖远程 ASR/TTS/LLM 服务；服务不可用时请求失败并记录错误。",
        "课程版使用 SQLite 与单管理员口令；企业级阶段应升级 PostgreSQL、RBAC 与监控告警。",
    ]

    next_steps = [
        "启动 remote/start_lora_llm.sh，并运行 check_real_service_chain.py --require-lora 生成当前 LoRA 全链路证据。",
        "扩展真实端到端评测到至少 30 条录音，并按 ASR、LLM、TTS 阶段拆分指标。",
        "替换或优化 TTS，让首音延迟从 15 秒级降到 3 秒以内。",
        "把 citation 质量评测扩展到更多真实规程来源，并增加来源可信度评分。",
        "把管理后台的评测任务结果接入本验收报告，形成网页内一键验收。",
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git": {
            "branch": git_value(["branch", "--show-current"]),
            "commit": git_value(["rev-parse", "--short", "HEAD"]),
            "source_tree_dirty": source_tree_dirty(),
            "dirty_ignored_paths": sorted(DIRTY_STATUS_IGNORE_PATHS | set(DIRTY_STATUS_IGNORE_PREFIXES)),
        },
        "summary": {
            "project": "ShipVoice 船厂安全实时语音问答助手",
            "assessment": (
                "当前项目主体工程、RAG、安全门控、后台审计和 LoRA 实验已具备课程高分基础；"
                "若完成 ShipVoice LoRA 在线链路验收，可进入 95+ 档。"
                if not lora_chain_verified
                else "当前项目已具备课程 95+ 主要工程与实验证据；比赛级仍需扩展真实端到端压测、真实规程来源和 TTS 延迟优化。"
            ),
            "recommended_course_score": 94 if not lora_chain_verified else 97,
            "knowledge_records": knowledge_count,
        },
        "capabilities": capabilities,
        "metrics": metrics,
        "artifacts": artifacts,
        "limitations": limitations,
        "next_steps": next_steps,
    }


def render_markdown(report: dict[str, Any]) -> str:
    current_lora_verified = bool(report["metrics"]["real_chain_smoke"]["verified_lora_chain"])
    if current_lora_verified:
        multiturn_result = (
            f"对话 {report['metrics']['multiturn']['dialogs']}，轮次 {report['metrics']['multiturn']['turns']}，"
            f"follow-up grounding {pct(report['metrics']['multiturn']['followup_grounding_accuracy'])}，"
            f"关键词召回 {pct(report['metrics']['multiturn']['keyword_recall'])}"
        )
        citation_result = (
            f"样本 {report['metrics']['citation_quality']['total']}，允许引用样本 {report['metrics']['citation_quality']['allowed_cases']}，"
            f"title hit@1 {pct(report['metrics']['citation_quality']['citation_title_hit_at_1'])}，"
            f"title hit@3 {pct(report['metrics']['citation_quality']['citation_title_hit_at_3'])}，"
            f"ID hit@3 {pct(report['metrics']['citation_quality']['citation_id_hit_at_3'])}，"
            f"Top-1 schema {pct(report['metrics']['citation_quality']['top1_schema_completeness'])}，"
            f"答案引用 ID {pct(report['metrics']['citation_quality']['answer_citation_id_rate'])}"
        )
    else:
        multiturn_result = "待 ShipVoice LoRA 在线链路重跑；旧结果不计入当前最终验收。"
        citation_result = "待 ShipVoice LoRA 在线链路重跑；当前仅保留证据结构测试和前端证据展示能力。"
    lines = [
        "# ShipVoice 项目验收报告",
        "",
        f"- 生成时间：`{report['generated_at']}`",
        f"- Git 分支：`{report['git']['branch'] or 'unknown'}`",
        f"- Git 提交：`{report['git']['commit'] or 'unknown'}`",
        f"- 源代码工作区是否有未提交改动：`{report['git']['source_tree_dirty']}`",
        f"- 建议课程目标分：`{report['summary']['recommended_course_score']} / 100`",
        "",
        "## 总体结论",
        "",
        report["summary"]["assessment"],
        "",
        "## 能力验收",
        "",
        "| 能力 | 状态 | 证据 | 说明 |",
        "|---|---|---|---|",
    ]
    for item in report["capabilities"]:
        evidence = "<br>".join(f"`{path}`" for path in item["evidence"])
        lines.append(f"| {item['name']} | `{item['status']}` | {evidence} | {item['notes']} |")

    metrics = report["metrics"]
    lines.extend(
        [
            "",
            "## 关键指标",
            "",
            "| 指标组 | 结果 |",
            "|---|---|",
            f"| 安全门控 | 样本 {metrics['safety_gate']['total']}，决策准确率 {pct(metrics['safety_gate']['decision_accuracy'])}，false allow {metrics['safety_gate']['false_allow_count']}，false block {metrics['safety_gate']['false_block_count']} |",
            f"| 多轮问答 | {multiturn_result} |",
            f"| Citation 质量 | {citation_result} |",
            f"| ASR 清单 | 已评测 {metrics['asr_manifest']['evaluated_rows']} 条，缺失音频 {metrics['asr_manifest']['missing_audio_rows']}，术语召回 {pct(metrics['asr_manifest']['term_recall'])}，状态 `{metrics['asr_manifest']['status']}` |",
            f"| 当前真实链路 | LoRA 在线验收 `{metrics['real_chain_smoke']['verified_lora_chain']}`，样本 `{metrics['real_chain_smoke']['sample_id'] or 'n/a'}`，ASR {ms(metrics['real_chain_smoke']['asr_ms'])}，检索 {ms(metrics['real_chain_smoke']['retrieval_ms'])}，LLM 首 token {ms(metrics['real_chain_smoke']['llm_first_token_ms'])}，TTS 首音 {ms(metrics['real_chain_smoke']['tts_first_audio_ms'])}，端到端首音 {ms(metrics['real_chain_smoke']['first_audio_ms'])} |",
            f"| LoRA 实验 | 训练 {metrics['lora_experiment']['train_examples']} 条，holdout {metrics['lora_experiment']['holdout_examples']} 条，base/lora 评测 {metrics['lora_experiment']['base_rows']}/{metrics['lora_experiment']['lora_rows']}，train loss {metrics['lora_experiment']['train_loss']}，adapter {metrics['lora_experiment']['adapter_mb']} MB，off-domain 拒答 {metrics['lora_experiment']['base_off_domain_refusal_count']} -> {metrics['lora_experiment']['lora_off_domain_refusal_count']} |",
            "",
            "## 交付物检查",
            "",
            "| 文件 | 状态 | 大小 |",
            "|---|---|---:|",
        ]
    )
    for artifact in report["artifacts"]:
        state = "存在" if artifact["exists"] else "缺失"
        lines.append(f"| `{artifact['path']}` | {state} | {artifact['bytes']} |")

    lines.extend(["", "## 当前边界", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(["", "## 下一步", ""])
    lines.extend(f"- {item}" for item in report["next_steps"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a ShipVoice acceptance report from local evidence files.")
    parser.add_argument("--json", default=str(REPORT_JSON), help="Output JSON path.")
    parser.add_argument("--markdown", default=str(REPORT_MD), help="Output Markdown path.")
    args = parser.parse_args()

    report = build_report()
    json_path = Path(args.json)
    md_path = Path(args.markdown)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
