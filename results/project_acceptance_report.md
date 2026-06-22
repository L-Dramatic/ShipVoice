# ShipVoice 项目验收报告

- 生成时间：`2026-06-22T07:39:26.421540+00:00`
- Git 分支：`codex/phase1-enterprise-backend`
- Git 提交：`21c2db8`
- 源代码工作区是否有未提交改动：`True`
- 建议课程目标分：`97 / 100`

## 总体结论

当前项目已具备课程 95+ 主要工程与实验证据；比赛级仍需扩展真实端到端压测、真实规程来源和 TTS 延迟优化。

## 能力验收

| 能力 | 状态 | 证据 | 说明 |
|---|---|---|---|
| 用户端语音/文本问答 | `implemented` | `web/static/index.html`<br>`src/shipvoice/fastapi_app.py` | 支持文本输入、音频上传、浏览器直接录音、TTS 播放。 |
| ASR -> 安全门控 -> RAG -> LLM -> TTS 主链路 | `implemented` | `src/shipvoice/pipeline.py`<br>`src/shipvoice/providers.py` | 采用真实 provider 与 fail-closed 策略；ASR、LLM、TTS 服务缺失时请求失败并记录错误。 |
| ShipVoice LoRA 在线推理服务 | `implemented` | `remote/serve_transformers_openai.py`<br>`remote/start_lora_llm.sh`<br>`remote/stop_lora_llm.sh` | 远端服务可强制加载 LoRA adapter；adapter 不存在或未加载时启动失败。 |
| 管理后台与审计 | `implemented` | `web/static/admin.html`<br>`src/shipvoice/sqlite_store.py`<br>`tests/test_admin_api.py` | 知识库治理、运行记录、case ledger、评测任务、导出能力已接入。 |
| 领域知识库与 RAG | `implemented` | `data/knowledge/ship_safety_corpus.jsonl`<br>`data/knowledge/ship_safety_index.json` | 当前知识条目 20 条；回答侧返回知识 ID、来源、风险级别、匹配词和置信度。 |
| 安全评测闭环 | `implemented` | `data/tests/safety_eval.csv`<br>`results/safety_gate_eval_summary.json` | 55 条安全样本，决策准确率 100.0%。 |
| 可解释证据引用 | `implemented` | `src/shipvoice/providers.py`<br>`web/static/app.js`<br>`scripts/evaluate_citation_quality.py`<br>`results/citation_quality_summary.json`<br>`tests/test_evidence_citations.py` | 当前 LoRA 链路 citation title hit@3 100.0%，Top-1 schema 完整率 100.0%。 |
| 当前真实语音链路验收 | `verified_lora_chain` | `scripts/check_real_service_chain.py`<br>`results/real_chain_smoke.json` | 当前 real_chain_smoke 已确认 ShipVoice LoRA adapter 在线加载。 |
| 微调与安全数据资产 | `completed_experiment` | `data/training/shipvoice_sft_train_expanded.jsonl`<br>`remote/train_qwen_lora.py`<br>`results/remote_autodl_20260621_expanded/summary.json` | 扩展 SFT 1000 条，holdout 150 条；LoRA train loss 0.1676858789101243，adapter 约 154.1 MB。 |
| 容器化与远程部署 | `implemented` | `Dockerfile`<br>`docker-compose.app.yml`<br>`remote/start_shipvoice_real_services.sh` | 支持本地 FastAPI 应用、Docker 运行、AutoDL 真实模型服务脚本。 |

## 关键指标

| 指标组 | 结果 |
|---|---|
| 安全门控 | 样本 55，决策准确率 100.0%，false allow 0，false block 0 |
| 多轮问答 | 对话 6，轮次 18，follow-up grounding 100.0%，关键词召回 78.2% |
| Citation 质量 | 样本 8，允许引用样本 5，title hit@1 100.0%，title hit@3 100.0%，ID hit@3 100.0%，Top-1 schema 100.0%，答案引用 ID 100.0% |
| ASR 清单 | 已评测 50 条，缺失音频 0，术语召回 100.0%，状态 `ready` |
| 当前真实链路 | LoRA 在线验收 `True`，样本 `A001`，ASR 121 ms，检索 5 ms，LLM 首 token 5038 ms，TTS 首音 3294 ms，端到端首音 8459 ms |
| LoRA 实验 | 训练 1000 条，holdout 150 条，base/lora 评测 150/150，train loss 0.1676858789101243，adapter 154.1 MB，off-domain 拒答 1 -> 10 |

## 交付物检查

| 文件 | 状态 | 大小 |
|---|---|---:|
| `README.md` | 存在 | 8502 |
| `docs/PHASE1_SCORECARD.md` | 存在 | 1237 |
| `docs/OPERATIONS_RUNBOOK.md` | 存在 | 2532 |
| `docs/ARCHITECTURE.md` | 存在 | 2609 |
| `results/citation_quality_report.md` | 存在 | 1244 |
| `results/citation_quality_summary.json` | 存在 | 495 |
| `results/citation_quality_eval.csv` | 存在 | 5281 |
| `deliverables/ShipVoice_Evaluation_Dashboard.html` | 存在 | 19096 |
| `deliverables/ShipVoice_Final_Defense_Deck_Draft.pptx` | 存在 | 236491 |
| `deliverables/ShipVoice_船厂安全实时语音问答助手_项目报告_比赛增强版.docx` | 存在 | 48280 |
| `web/static/index.html` | 存在 | 9775 |
| `web/static/admin.html` | 存在 | 14688 |
| `Dockerfile` | 存在 | 286 |

## 当前边界

- 当前本地证据必须重新跑 ShipVoice LoRA 在线链路验收，不能再使用旧基座模型结果代表最终系统。
- 真实端到端语音链路尚未扩展到 30+ 条真实端到端压测。
- TTS 首音延迟仍需优化，答辩时应如实说明瓶颈在 TTS 服务。
- 当前 real-only 版本依赖远程 ASR/TTS/LLM 服务；服务不可用时请求失败并记录错误。
- 课程版使用 SQLite 与单管理员口令；企业级阶段应升级 PostgreSQL、RBAC 与监控告警。

## 下一步

- 启动 remote/start_lora_llm.sh，并运行 check_real_service_chain.py --require-lora 生成当前 LoRA 全链路证据。
- 扩展真实端到端评测到至少 30 条录音，并按 ASR、LLM、TTS 阶段拆分指标。
- 替换或优化 TTS，让首音延迟从 15 秒级降到 3 秒以内。
- 把 citation 质量评测扩展到更多真实规程来源，并增加来源可信度评分。
- 把管理后台的评测任务结果接入本验收报告，形成网页内一键验收。
