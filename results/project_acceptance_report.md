# ShipVoice 项目验收报告

- 生成时间：`2026-06-23T17:10:36.185440+00:00`
- Git 分支：`main`
- Git 提交：`e23fd7b`
- 源代码工作区是否有未提交改动：`True`
- 建议课程目标分：`97 / 100`

## 总体结论

当前项目已具备课程 95+ 主要工程与实验证据；比赛级仍需扩展真实生产场景压测、真实规程来源和 TTS 延迟优化。

## 能力验收

| 能力 | 状态 | 证据 | 说明 |
|---|---|---|---|
| 用户端语音/文本问答 | `implemented` | `web/static/index.html`<br>`src/shipvoice/fastapi_app.py` | 支持文本输入、音频上传、浏览器直接录音、TTS 播放。 |
| ASR -> 安全门控 -> RAG -> LLM -> TTS 主链路 | `implemented` | `src/shipvoice/pipeline.py`<br>`src/shipvoice/providers.py` | 采用真实 provider 与 fail-closed 策略；ASR、LLM、TTS 服务缺失时请求失败并记录错误。 |
| ShipVoice LoRA 在线推理服务 | `implemented` | `remote/serve_transformers_openai.py`<br>`remote/start_lora_llm.sh`<br>`remote/stop_lora_llm.sh` | 远端服务可强制加载 LoRA adapter；adapter 不存在或未加载时启动失败。 |
| 管理后台与审计 | `implemented` | `web/static/admin.html`<br>`src/shipvoice/sqlite_store.py`<br>`tests/test_admin_api.py` | 知识库治理、运行记录、case ledger、评测任务、导出能力已接入。 |
| 领域知识库与 RAG | `implemented` | `data/knowledge/ship_safety_corpus.jsonl`<br>`data/knowledge/ship_safety_index.json` | 当前知识条目 20 条；回答侧返回知识 ID、来源、风险级别、匹配词和置信度。 |
| 安全评测闭环 | `implemented` | `data/tests/safety_eval.csv`<br>`results/safety_gate_eval_summary.json` | 56 条安全样本，决策准确率 100.0%。 |
| 可解释证据引用 | `implemented` | `src/shipvoice/providers.py`<br>`web/static/app.js`<br>`scripts/evaluate_citation_quality.py`<br>`results/citation_quality_summary.json`<br>`tests/test_evidence_citations.py` | 当前 LoRA 链路 citation title hit@3 100.0%，Top-1 schema 完整率 100.0%。 |
| 当前真实语音链路验收 | `verified_real_repeated` | `scripts/run_real_chain_repeated.py`<br>`results/server_real_repeated_20260623/summary.json`<br>`results/server_real_batch_comparison_20260623.json`<br>`results/browser_onplaying_streamable_20260623.json` | 真实链路重复实验 300 次全部成功，ShipVoice LoRA adapter 在线加载。 |
| 固定音频集与等待体验量化 | `implemented` | `data/audio/audio_manifest_a2_eval.csv`<br>`docs/FIXED_AUDIO_COMMAND_SET_20260623.md`<br>`scripts/evaluate_waiting_experience.py`<br>`results/waiting_experience_20260623/summary.json` | 50 条录音已按 A2 难度梯度分层；等待体验采用真实延迟日志生成代理评分，不伪造真人问卷。 |
| 微调与安全数据资产 | `completed_experiment` | `data/training/shipvoice_sft_train_expanded.jsonl`<br>`remote/train_qwen_lora.py`<br>`results/remote_autodl_20260621_expanded/summary.json`<br>`results/remote_lora_expanded_summary_20260621.json` | 扩展 SFT 1000 条，holdout 150 条；LoRA train loss 0.1676858789101243，adapter 约 154.1 MB。 |
| 容器化与远程部署 | `implemented` | `Dockerfile`<br>`docker-compose.app.yml`<br>`remote/start_shipvoice_real_services.sh` | 支持本地 FastAPI 应用、Docker 运行、AutoDL 真实模型服务脚本。 |

## 关键指标

| 指标组 | 结果 |
|---|---|
| 安全门控 | 样本 56，决策准确率 100.0%，false allow 0，false block 0 |
| 多轮问答 | 对话 6，轮次 18，follow-up grounding 100.0%，关键词召回 73.6% |
| Citation 质量 | 样本 8，允许引用样本 5，title hit@1 100.0%，title hit@3 100.0%，ID hit@3 100.0%，Top-1 schema 100.0%，答案引用 ID 100.0% |
| ASR 清单 | 已评测 50 条，缺失音频 0，术语召回 100.0%，状态 `ready` |
| 真实链路重复实验 | 运行 300 次，成功 300 次，失败 0 次；baseline 首播均值 7967 ms，streaming 首播均值 3820 ms，平均节省 4147 ms，更快配对 100 / 100 |
| 浏览器首播观测 | 样本 20，成功 20，失败 0，audio.onplaying 均值 4094 ms，P50 4072 ms，P90 5600 ms |
| 等待体验代理评分 | baseline 2.02 / 5，streaming 3.71 / 5，浏览器 streaming 3.6 / 5 |
| LoRA 实验 | 训练 1000 条，holdout 150 条，base/lora 评测 150/150，train loss 0.1676858789101243，adapter 154.1 MB，off-domain 拒答 1 -> 10 |

## 交付物检查

| 文件 | 状态 | 大小 |
|---|---|---:|
| `README.md` | 存在 | 10432 |
| `docs/PHASE1_SCORECARD.md` | 存在 | 3318 |
| `docs/OPERATIONS_RUNBOOK.md` | 存在 | 4613 |
| `docs/ARCHITECTURE.md` | 存在 | 7350 |
| `docs/A2_REQUIREMENT_COMPLETION_AUDIT_20260623.md` | 存在 | 8918 |
| `docs/FIXED_AUDIO_COMMAND_SET_20260623.md` | 存在 | 11046 |
| `data/audio/audio_manifest_a2_eval.csv` | 存在 | 26824 |
| `results/citation_quality_report.md` | 存在 | 1272 |
| `results/citation_quality_summary.json` | 存在 | 510 |
| `results/citation_quality_eval.csv` | 存在 | 5283 |
| `results/server_real_repeated_20260623/summary.json` | 存在 | 14363 |
| `results/server_real_batch_comparison_20260623.json` | 存在 | 7980 |
| `results/browser_onplaying_streamable_20260623.json` | 存在 | 13097 |
| `results/waiting_experience_20260623/summary.json` | 存在 | 4184 |
| `results/waiting_experience_20260623/report.md` | 存在 | 2955 |
| `deliverables/ShipVoice_Evaluation_Dashboard.html` | 存在 | 20324 |
| `deliverables/ShipVoice_Final_Defense_Deck_Draft.pptx` | 存在 | 236491 |
| `deliverables/final_submission/report/ShipVoice_船厂安全实时语音问答助手_项目报告_最终版.docx` | 存在 | 3377692 |
| `deliverables/final_submission/report/ShipVoice_船厂安全实时语音问答助手_项目报告_最终版.pdf` | 存在 | 3056052 |
| `deliverables/final_submission/report/ShipVoice_船厂安全实时语音问答助手_项目报告_最终版.md` | 存在 | 47204 |
| `web/static/index.html` | 存在 | 10384 |
| `web/static/admin.html` | 存在 | 15075 |
| `Dockerfile` | 存在 | 501 |

## 当前边界

- 真实端到端语音链路已经完成 300 次课程规模固定音频集重复实验，但还不是长期生产压测。
- 浏览器首播平均约 4 秒，已明显优于串行基线，但距离企业级自然接话体验仍有优化空间。
- 主观等待体验采用真实延迟日志的自动化代理评分，不是真人 Likert 问卷。
- 当前 real-only 版本依赖远程 ASR/TTS/LLM 服务；服务不可用时请求失败并记录错误。
- 课程版使用 SQLite 与单管理员口令；企业级阶段应升级 PostgreSQL、RBAC 与监控告警。

## 下一步

- 答辩前重新做 provider health 和一条 check_real_service_chain.py 探针，确认现场 ASR/LLM/TTS 在线。
- 把真实端到端评测扩展到更多说话人、更多噪声条件和更长多轮任务。
- 替换或优化 TTS，让浏览器首播进一步接近 2 秒内自然接话体验。
- 把 citation 质量评测扩展到更多真实规程来源，并增加来源可信度评分。
- 把管理后台的评测任务结果接入本验收报告，形成网页内一键验收。
