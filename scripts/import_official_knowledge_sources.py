from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shipvoice.sqlite_store import SQLiteAppStore  # noqa: E402

SOURCE_DIR = ROOT / "data" / "knowledge" / "official_sources"
OUTPUT_PATH = SOURCE_DIR / "official_evidence_records.jsonl"


ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百零〇两]+条")


def html_to_compact_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    raw = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", "", raw)


def extract_articles(path: Path) -> dict[str, str]:
    text = html_to_compact_text(path)
    starts = [match.start() for match in ARTICLE_RE.finditer(text)]
    articles: dict[str, str] = {}
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else min(len(text), start + 1800)
        chunk = text[start:end].strip()
        marker = ARTICLE_RE.match(chunk)
        if marker:
            articles[marker.group(0)] = chunk
    return articles


def clipped(text: str, limit: int = 520) -> str:
    text = re.sub(r"\s+", "", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    punctuation = max(cut.rfind("。"), cut.rfind("；"), cut.rfind(";"))
    if punctuation >= 240:
        return cut[: punctuation + 1]
    return cut.rstrip("，,；;、") + "。"


def record(
    record_id: str,
    title: str,
    tags: list[str],
    text: str,
    source: str,
    risk_level: str = "medium",
) -> dict[str, Any]:
    return {
        "id": record_id,
        "title": title,
        "tags": tags,
        "text": clipped(text),
        "status": "approved",
        "owner": "ShipVoice",
        "source": source,
        "risk_level": risk_level,
        "reviewer": "system",
        "review_notes": "官方来源扩展条目，保留原文摘要和来源链接，用于增强RAG依据可追溯性。",
        "change_note": "Import official evidence source",
    }


def build_records() -> list[dict[str, Any]]:
    limited_space_source = (
        "应急管理部令第13号《工贸企业有限空间作业安全规定》 "
        "https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202312/t20231208_471355.shtml"
    )
    safety_law_source = (
        "《中华人民共和国安全生产法》 "
        "https://www.mem.gov.cn/fw/flfgbz/fg/202107/t20210716_416558.shtml"
    )
    gb_source = (
        "国家标准全文公开系统 GB 30871-2022《危险化学品企业特殊作业安全规范》 "
        "https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=561B95121C30853A6B45CA9471F39239"
    )

    limited = extract_articles(SOURCE_DIR / "mem_limited_space_order_13.html")
    safety_law = extract_articles(SOURCE_DIR / "mem_safety_production_law_2021.html")

    specs: list[tuple[str, str, str, list[str], str, str]] = [
        ("OFF001", "有限空间定义与适用范围", "第三条", ["官方依据", "有限空间", "适用范围"], limited_space_source, "high"),
        ("OFF002", "有限空间第一责任人与制度要求", "第四条", ["官方依据", "有限空间", "责任制", "审批"], limited_space_source, "critical"),
        ("OFF003", "有限空间监护制与监护能力", "第五条", ["官方依据", "有限空间", "监护", "应急处置"], limited_space_source, "critical"),
        ("OFF004", "有限空间辨识与管理台账", "第六条", ["官方依据", "有限空间", "台账", "风险辨识"], limited_space_source, "high"),
        ("OFF005", "有限空间作业审批要求", "第七条", ["官方依据", "有限空间", "审批", "中毒窒息"], limited_space_source, "critical"),
        ("OFF006", "承包有限空间作业的统一协调管理", "第八条", ["官方依据", "有限空间", "承包管理", "安全检查"], limited_space_source, "high"),
        ("OFF007", "有限空间年度专题培训", "第九条", ["官方依据", "有限空间", "培训", "应急救援"], limited_space_source, "medium"),
        ("OFF008", "有限空间现场处置方案与演练", "第十条", ["官方依据", "有限空间", "现场处置", "演练"], limited_space_source, "high"),
        ("OFF009", "有限空间警示标志与风险告知", "第十一条", ["官方依据", "有限空间", "警示标志", "风险告知"], limited_space_source, "medium"),
        ("OFF010", "有限空间物理隔离", "第十二条", ["官方依据", "有限空间", "隔离", "未经审批进入"], limited_space_source, "high"),
        ("OFF011", "有限空间检测通风与救援装备", "第十三条", ["官方依据", "有限空间", "气体检测", "通风", "呼吸防护"], limited_space_source, "critical"),
        ("OFF012", "先通风再检测后作业", "第十四条", ["官方依据", "有限空间", "通风", "检测", "安全交底"], limited_space_source, "critical"),
        ("OFF013", "有限空间全过程监护与撤离", "第十五条", ["官方依据", "有限空间", "持续通风", "持续检测", "撤离"], limited_space_source, "critical"),
        ("OFF014", "有限空间重大隐患停工处置", "第十八条", ["官方依据", "有限空间", "重大隐患", "停工"], limited_space_source, "critical"),
        ("OFF015", "有限空间违法情形：设备与警示", "第十九条", ["官方依据", "有限空间", "警示标志", "设备维护"], limited_space_source, "medium"),
        ("OFF016", "有限空间违法情形：培训与演练", "第二十条", ["官方依据", "有限空间", "培训", "演练"], limited_space_source, "medium"),
        ("OFF017", "有限空间违法情形：审批通风检测", "第二十一条", ["官方依据", "有限空间", "审批", "通风", "检测"], limited_space_source, "critical"),
        ("OFF018", "安全生产基本方针与责任机制", "第三条", ["官方依据", "安全生产法", "预防为主", "主体责任"], safety_law_source, "medium"),
        ("OFF019", "生产经营单位安全管理与双重预防", "第四条", ["官方依据", "安全生产法", "责任制", "隐患排查"], safety_law_source, "high"),
        ("OFF020", "主要负责人安全生产责任", "第五条", ["官方依据", "安全生产法", "第一责任人"], safety_law_source, "medium"),
        ("OFF021", "从业人员安全权利与义务", "第六条", ["官方依据", "安全生产法", "从业人员", "权利义务"], safety_law_source, "medium"),
        ("OFF022", "国家标准和行业标准执行要求", "第十一条", ["官方依据", "安全生产法", "国家标准", "行业标准"], safety_law_source, "medium"),
        ("OFF023", "不具备安全生产条件不得生产经营", "第二十条", ["官方依据", "安全生产法", "安全条件"], safety_law_source, "high"),
        ("OFF024", "主要负责人七项职责", "第二十一条", ["官方依据", "安全生产法", "负责人职责", "应急预案"], safety_law_source, "high"),
        ("OFF025", "全员安全生产责任制", "第二十二条", ["官方依据", "安全生产法", "全员责任制", "考核"], safety_law_source, "medium"),
        ("OFF026", "安全管理机构职责", "第二十五条", ["官方依据", "安全生产法", "安全管理", "隐患排查"], safety_law_source, "high"),
        ("OFF027", "从业人员教育培训", "第二十八条", ["官方依据", "安全生产法", "培训", "上岗"], safety_law_source, "medium"),
        ("OFF028", "特种作业人员持证上岗", "第三十条", ["官方依据", "安全生产法", "特种作业", "持证"], safety_law_source, "high"),
        ("OFF029", "安全设备维护检测", "第三十六条", ["官方依据", "安全生产法", "安全设备", "维护检测"], safety_law_source, "high"),
        ("OFF030", "重大危险源登记建档与应急措施", "第四十条", ["官方依据", "安全生产法", "重大危险源", "应急措施"], safety_law_source, "critical"),
        ("OFF031", "风险分级管控与隐患排查治理", "第四十一条", ["官方依据", "安全生产法", "风险分级", "隐患排查"], safety_law_source, "high"),
        ("OFF032", "危险作业现场安全管理", "第四十三条", ["官方依据", "安全生产法", "吊装", "动火", "临时用电"], safety_law_source, "critical"),
        ("OFF033", "从业人员了解危险因素与应急措施", "第四十四条", ["官方依据", "安全生产法", "危险因素", "应急措施"], safety_law_source, "medium"),
        ("OFF034", "安全防护用品配备和使用", "第四十五条", ["官方依据", "安全生产法", "PPE", "防护用品"], safety_law_source, "medium"),
        ("OFF035", "从业人员拒绝违章指挥和强令冒险", "第五十一条", ["官方依据", "安全生产法", "拒绝违章", "冒险作业"], safety_law_source, "high"),
        ("OFF036", "事故应急预案与定期演练", "第八十一条", ["官方依据", "安全生产法", "应急预案", "演练"], safety_law_source, "high"),
    ]

    records: list[dict[str, Any]] = []
    for record_id, title, article_no, tags, source, risk_level in specs:
        article_map = limited if "有限空间" in source else safety_law
        article = article_map.get(article_no)
        if not article:
            raise RuntimeError(f"missing article {article_no} for {record_id}")
        records.append(record(record_id, title, tags, article, source, risk_level))

    records.append(
        record(
            "OFF037",
            "GB 30871-2022 特殊作业标准元数据",
            ["官方依据", "GB30871", "特殊作业", "动火", "受限空间"],
            (
                "国家标准全文公开系统显示，GB 30871-2022 的中文标准名称为《危险化学品企业特殊作业安全规范》，"
                "标准状态为现行，发布日期为2022-03-15，实施日期为2022-10-01，主管部门和归口部门为应急管理部。"
                "ShipVoice 在船厂场景引用该标准时仅作为特殊作业安全管理参考依据，并在回答中避免把危化企业标准直接泛化为所有船厂作业的唯一强制依据。"
            ),
            gb_source,
            "medium",
        )
    )
    records.append(
        record(
            "OFF038",
            "官方依据适用范围提示",
            ["官方依据", "适用范围", "证据边界", "回答规范"],
            (
                "官方法规和标准进入知识库后，系统回答应同时说明适用范围和证据边界："
                "有限空间问题优先引用《工贸企业有限空间作业安全规定》；生产经营单位主体责任、培训、隐患排查、危险作业现场管理等上位要求可引用《安全生产法》；"
                "GB 30871-2022 可作为动火、受限空间、吊装、临时用电等特殊作业管理参考，但应标注其危险化学品企业适用背景。"
            ),
            "ShipVoice 官方依据整理规则",
            "medium",
        )
    )
    return records


def main() -> None:
    records = build_records()
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
        encoding="utf-8",
    )

    store = SQLiteAppStore()
    for item in records:
        store.upsert_knowledge(item, record_id=item["id"])

    summary = store.knowledge_summary()
    print(
        json.dumps(
            {
                "imported": len(records),
                "output": str(OUTPUT_PATH),
                "knowledge_record_count": summary["record_count"],
                "approved_count": summary["approved_count"],
                "index_path": summary["index_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
