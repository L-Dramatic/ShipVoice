# ShipVoice 提交说明

## 当前交付物

- `ShipVoice_船厂安全实时语音问答助手_项目报告_初稿.docx`
- `ShipVoice_船厂安全实时语音问答助手_项目报告_比赛增强版.docx`
- `ShipVoice_Final_Defense_Deck_Draft.pptx`
- `ShipVoice_Evaluation_Dashboard.html`
- `ShipVoice_Audio_Recording_Pack.html`

## 建议最终提交包结构

```text
ShipVoice_Final_Submission/
  README.md
  report/
    ShipVoice_船厂安全实时语音问答助手_项目报告_比赛增强版.docx
    ShipVoice_船厂安全实时语音问答助手_项目报告.pdf
  slides/
    ShipVoice_船厂安全实时语音问答助手_答辩PPT.pptx
  source/
    configs/
    data/
    docs/
    remote/
    scripts/
    src/
    web/
    README.md
    requirements.txt
    run_demo.py
  evidence/
    results/latency_metrics.csv
    results/safety_gate_eval.csv
    results/safety_gate_eval_summary.json
    results/safety_gate_eval_report.md
    results/asr_eval.csv
    results/asr_eval_summary.json
    results/asr_eval_report.md
    results/demo_panel_safety.png
    results/demo_panel_backend.png
    results/remote_lora_expanded_summary_20260621.json
    data/training/shipvoice_sft_train_expanded.jsonl
    data/training/shipvoice_sft_eval_holdout.jsonl
  competition_docs/
    docs/COMPETITION_GRADE_ROADMAP.md
    docs/DATA_CARD.md
    docs/MODEL_CARD.md
    docs/DEMO_VIDEO_SCRIPT.md
    deliverables/ShipVoice_Audio_Recording_Pack.html
```

## 最后需要补充

- 小组成员姓名和学号
- 是否需要按老师要求改文件名
- 若老师要求展示原始音频，可从 `data/audio/raw/` 中选取代表性样例演示
- 录制 2.5-3.5 分钟答辩演示视频
- 如果要 PDF，需要用本机 Word 或 WPS 将 DOCX 导出为 PDF

## 推荐答辩口径

本项目不是简单把 ASR、LLM、TTS 串起来，而是在船厂安全这一高风险领域里加入了安全门控、RAG 证据检索、可运行演示、可复现实验和 Qwen LoRA 微调对照。LoRA 是加分实验，正式系统的安全边界仍由门控和证据层保证。

## 当前比赛级补强进展

- 已新增 55 条安全/离题/prompt-injection/domain-safe/boundary benchmark，并完成完整 pipeline 评测。
- 当前安全门控评测：标签准确率 100%，allow/block 决策准确率 100%，危险请求误放行 0。
- 已将安全评测、延迟评测、RAG 证据、LoRA 远端实验汇总到 `ShipVoice_Evaluation_Dashboard.html`。
- 已完成 50 条真实语音的 SenseVoice ASR 实测，并加入术语后处理增强；当前 raw 基线为 CER/WER 1.58%、术语召回 85.71%，增强后 `results/asr_eval_summary.json` 为 CER/WER 0.00%、术语召回 100.00%。
- 下一批关键补强是录制真实音频、填入 ASR 转写、扩充 100+ QA 与 100+ 对抗安全样例，并制作演示视频。
