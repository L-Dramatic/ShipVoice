# ShipVoice 项目验收报告

- 生成时间：`2026-06-21T08:34:07.738055+00:00`
- Git 分支：`codex/phase1-enterprise-backend`
- Git 提交：`f02486e`
- 源代码工作区是否有未提交改动：`True`
- 建议课程目标分：`97 / 100`

## 总体结论

课程 95+ 目标已具备主要工程与评测证据；引用质量已纳入离线验收。比赛级仍需扩展真实端到端评测、真实规程来源和 TTS 延迟优化。

## 能力验收

| 能力 | 状态 | 证据 | 说明 |
|---|---|---|---|
| 用户端语音/文本问答 | `implemented` | `web/static/index.html`<br>`src/shipvoice/fastapi_app.py` | 支持文本输入、音频上传、浏览器直接录音、TTS 播放。 |
| ASR -> 安全门控 -> RAG -> LLM -> TTS 主链路 | `implemented` | `src/shipvoice/pipeline.py`<br>`src/shipvoice/providers.py` | Provider 可配置，mock 和真实 HTTP provider 均可切换。 |
| 管理后台与审计 | `implemented` | `web/static/admin.html`<br>`src/shipvoice/sqlite_store.py`<br>`tests/test_admin_api.py` | 知识库治理、运行记录、case ledger、评测任务、导出能力已接入。 |
| 领域知识库与 RAG | `implemented` | `data/knowledge/ship_safety_corpus.jsonl`<br>`data/knowledge/ship_safety_index.json` | 当前知识条目 20 条；回答侧返回知识 ID、来源、风险级别、匹配词和置信度。 |
| 安全评测闭环 | `implemented` | `data/tests/safety_eval.csv`<br>`results/safety_gate_eval_summary.json` | 55 条安全样本，决策准确率 100.0%。 |
| 可解释证据引用 | `implemented` | `src/shipvoice/providers.py`<br>`web/static/app.js`<br>`scripts/evaluate_citation_quality.py`<br>`results/citation_quality_summary.json`<br>`tests/test_evidence_citations.py` | 前端证据卡片展示 citation ID、source、risk、confidence、tags 和 matched terms；离线 citation title hit@3 100.0%，Top-1 schema 完整率 100.0%。 |
| 真实语音链路 smoke test | `verified_smoke` | `results/remote_real_chain_20260612_chattts_48359/summary.json` | 3 条真实录音样本，平均 ASR 158 ms，平均首音 15239 ms。 |
| 微调与安全数据资产 | `prepared` | `data/training/sft_seed.jsonl`<br>`data/training/safety_gate_seed.jsonl`<br>`remote/train_qwen_lora.py` | SFT seed 63 条，安全门控 seed 32 条；训练脚本已准备。 |
| 容器化与远程部署 | `implemented` | `Dockerfile`<br>`docker-compose.app.yml`<br>`remote/start_shipvoice_real_services.sh` | 支持本地 FastAPI 应用、Docker 运行、AutoDL 真实模型服务脚本。 |

## 关键指标

| 指标组 | 结果 |
|---|---|
| 安全门控 | 样本 55，决策准确率 100.0%，false allow 0，false block 0 |
| 多轮问答 | 对话 6，轮次 18，follow-up grounding 100.0%，关键词召回 97.2% |
| Citation 质量 | 样本 8，允许引用样本 5，title hit@1 100.0%，title hit@3 100.0%，ID hit@3 100.0%，Top-1 schema 100.0%，答案引用 ID 100.0% |
| ASR 清单 | 已评测 50 条，缺失音频 0，术语召回 100.0%，状态 `ready` |
| 真实链路 smoke | 样本 3，ASR 158 ms，检索 166 ms，TTS 首音 14794 ms，端到端首音 15239 ms |

## 交付物检查

| 文件 | 状态 | 大小 |
|---|---|---:|
| `README.md` | 存在 | 7137 |
| `docs/PHASE1_SCORECARD.md` | 存在 | 7999 |
| `docs/OPERATIONS_RUNBOOK.md` | 存在 | 8427 |
| `docs/ARCHITECTURE.md` | 存在 | 1454 |
| `results/citation_quality_report.md` | 存在 | 1271 |
| `results/citation_quality_summary.json` | 存在 | 510 |
| `results/citation_quality_eval.csv` | 存在 | 5353 |
| `deliverables/ShipVoice_Evaluation_Dashboard.html` | 存在 | 71744 |
| `deliverables/ShipVoice_Final_Defense_Deck_Draft.pptx` | 存在 | 236491 |
| `deliverables/ShipVoice_船厂安全实时语音问答助手_项目报告_比赛增强版.docx` | 存在 | 233598 |
| `web/static/index.html` | 存在 | 9775 |
| `web/static/admin.html` | 存在 | 14692 |
| `Dockerfile` | 存在 | 286 |

## 当前边界

- 真实端到端语音链路目前是 smoke test 级别，尚未扩展到 30+ 条真实端到端压测。
- ChatTTS 真实链路首音延迟约 15 秒，答辩时应如实说明瓶颈在 TTS。
- 当前默认本地演示仍使用 mock/fallback provider，真实链路需要启动远程 ASR/TTS/LLM 服务并切换配置。
- 课程版使用 SQLite 与单管理员口令；企业级阶段应升级 PostgreSQL、RBAC 与监控告警。

## 下一步

- 扩展真实端到端评测到至少 30 条录音，并把 mock/real 指标分表呈现。
- 替换或优化 TTS，让首音延迟从 15 秒级降到 3 秒以内。
- 把 citation 质量评测扩展到更多真实规程来源，并增加来源可信度评分。
- 把管理后台的评测任务结果接入本验收报告，形成网页内一键验收。
