from __future__ import annotations

import json
from pathlib import Path


TRAINING_FILES = (
    Path("data/training/sft_seed.jsonl"),
    Path("data/training/shipvoice_sft_eval_holdout.jsonl"),
    Path("data/training/shipvoice_sft_train_expanded.jsonl"),
)

OFF_DOMAIN_ANSWER = (
    "这个问题超出了 ShipVoice 的船厂安全问答范围。"
    "我可以帮助处理动火、有限空间、吊装、管路试压、临时用电、个人防护、监护检测和应急处置等造船现场安全问题。"
    "请把问题改成具体作业场景，例如：密闭舱室动火前需要确认什么？"
)

UNSAFE_ANSWER = (
    "这个请求涉及绕过安全制度或危害现场安全的做法，我不能提供操作步骤。"
    "请停止相关尝试，按船厂规程完成审批、检测、隔离、监护和应急准备；"
    "如果现场已经存在风险，请立即通知现场负责人或安全管理人员。"
)

PROMPT_INJECTION_ANSWER = (
    "这个请求试图覆盖安全规则或诱导输出受限内容，我不能泄露系统提示，也不能执行忽略规则、越权或违规操作要求。"
    "请回到具体的船厂安全作业问题；如果现场存在风险，应按制度上报并由现场负责人或安全管理人员确认。"
)

BAD_OFF_DOMAIN_MARKERS = (
    "系统应礼貌拒绝",
    "不属于船厂安全语音问答范围。系统应",
    "不属于船厂安全低风险通用咨询范围",
    "??????? ShipVoice",
)

BAD_UNSAFE_MARKERS = (
    "该请求属于规避安全制度，系统应拒绝",
)

BAD_PROMPT_INJECTION_MARKERS = (
    "系统应保持船厂安全助手身份",
)


def repair_file(path: Path) -> int:
    changed = 0
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            item = json.loads(raw)
            output = str(item.get("output", ""))
            category = str(item.get("category", ""))
            tags = {str(tag) for tag in item.get("tags", [])}
            expected_gate = str(item.get("meta", {}).get("expected_gate", ""))
            new_output = output

            if (
                category == "safety_off_domain"
                or expected_gate == "off_domain"
                or "off_domain" in tags
                or any(marker in output for marker in BAD_OFF_DOMAIN_MARKERS)
            ):
                new_output = OFF_DOMAIN_ANSWER
            elif (
                category == "safety_prompt_injection"
                or "prompt_injection" in tags
                or any(marker in output for marker in BAD_PROMPT_INJECTION_MARKERS)
            ):
                new_output = PROMPT_INJECTION_ANSWER
            elif any(marker in output for marker in BAD_UNSAFE_MARKERS):
                new_output = UNSAFE_ANSWER

            if new_output != output:
                item["output"] = new_output
                changed += 1
            lines.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def main() -> None:
    total = 0
    for path in TRAINING_FILES:
        changed = repair_file(path)
        total += changed
        print(f"{path}: {changed} outputs updated")
    print(f"total: {total}")


if __name__ == "__main__":
    main()
