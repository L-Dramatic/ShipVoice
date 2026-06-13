# ShipVoice Phase 1 课程高分验收评分表

本文档用于答辩、代码验收和团队复盘。核心目标是让评审能快速确认：ShipVoice 不是单页演示，而是一个可运行、可配置、可评测、可审计的船厂安全语音问答系统。

## 总体判断

建议当前课程评分目标：96 / 100。

这个分数的依据不是页面观感，而是以下能力已经落地：

- 前端：用户语音/文本问答页面、管理后台页面。
- 后端：FastAPI 服务、主问答 API、Admin API、认证、配置热更新、评测任务、运行复盘。
- 模型链路：支持 mock provider 和真实 ASR / LLM / TTS provider 切换。
- 领域能力：船厂安全知识库、RAG 检索、安全门控、术语后处理、多轮上下文。
- 实验证据：ASR 清单评测、安全门控评测、多轮评测、真实语音链路 smoke test。
- 工程证据：Docker、运行手册、AutoDL 脚本、远程服务脚本、单元测试、审计日志和 SQLite 管理数据。

## 评分拆解

| 维度 | 建议得分 | 证据 | 说明 |
|---|---:|---|---|
| 选题价值与场景真实性 | 10 / 10 | `data/knowledge/ship_safety_corpus.jsonl`, `configs/pipeline.json` | 场景聚焦船厂安全作业，不是泛泛聊天机器人。知识、风险类别、术语、拒答策略都有领域约束。 |
| 级联式语音问答主链路 | 18 / 20 | `src/shipvoice/pipeline.py`, `src/shipvoice/providers.py`, `web/static/index.html` | 已有 ASR -> 后处理 -> 安全门控 -> RAG -> LLM -> TTS 的完整链路，并支持真实 provider。扣分点是当前真实端到端样本数仍偏少。 |
| 安全增强与信息安全相关性 | 15 / 15 | `results/safety_gate_eval_summary.json`, `data/tests/safety_eval.csv` | 55 条安全评测中门控决策准确率 1.0，覆盖 off-domain、unsafe、prompt injection、boundary 等类别。 |
| 领域知识与 RAG | 13 / 15 | `data/knowledge/`, `scripts/evaluate_retrieval.py`, `results/multiturn_eval_summary.json` | 有领域知识库、索引构建、检索评测和后台知识治理。后续可加 citation 级别证据定位和更多真实规程来源。 |
| 多轮问答与上下文能力 | 9 / 10 | `data/tests/multiturn_eval.jsonl`, `results/multiturn_eval_summary.json` | 6 组对话、18 轮评测，followup grounding accuracy 为 1.0。后续可扩到更多复杂任务流。 |
| 真实语音数据与评测闭环 | 12 / 15 | `data/audio/audio_manifest.csv`, `results/asr_eval_summary.json`, `results/remote_real_chain_20260612_chattts_48359/summary.json` | 50 条录音清单评测完整，真实远程链路已有 3 条样本 smoke test。高分足够，但比赛级还要扩大真实 ASR 批量评测。 |
| 工程化程度 | 14 / 15 | `src/shipvoice/fastapi_app.py`, `src/shipvoice/sqlite_store.py`, `Dockerfile`, `docker-compose.app.yml`, `tests/test_admin_api.py` | 已经有前后端、认证、后台、任务、SQLite、Docker、测试。扣分点是还未拆成独立生产服务和 PostgreSQL。 |
| 展示与可解释性 | 5 / 5 | `deliverables/`, `docs/`, `web/static/admin.html` | 有报告、答辩 PPT、评测 dashboard、录音任务包和管理后台。 |

## 关键验收证据

### 1. 应用是否真实存在

是。当前是一个前后端一体的 FastAPI 应用：

- 用户端入口：`/`
- 管理后台入口：`/admin.html`
- 主问答接口：`POST /api/run`
- 健康检查：`GET /api/health`
- 管理接口：`/api/admin/*`

本地启动方式：

```powershell
.\scripts\start_shipvoice_app.ps1 -Mode mock
```

或：

```powershell
python run_app.py
```

### 2. 是否只有网页演示

不是。网页只是操作入口，背后已经有完整服务层：

- `src/shipvoice/pipeline.py` 负责问答主链路。
- `src/shipvoice/providers.py` 负责 ASR / LLM / TTS / RAG provider 抽象。
- `src/shipvoice/fastapi_app.py` 负责 HTTP API、认证、后台任务。
- `src/shipvoice/sqlite_store.py` 负责知识治理、运行审计、评测任务、复盘台账。
- `scripts/` 下是评测、构建、远程链路检查脚本。

### 3. 是否接过真实模型链路

接过。远程真实链路证据在：

```text
results/remote_real_chain_20260612_chattts_48359/summary.json
```

该轮验证使用：

- ASR：FunASR / SenseVoiceSmall HTTP 服务。
- TTS：ChatTTS HTTP 服务。
- 样本：A001-A003 三条真实录音。
- 平均 ASR 耗时：158 ms。
- 平均检索耗时：165.67 ms。
- 平均首音频耗时：15238.67 ms。

需要如实说明：当前瓶颈主要是 ChatTTS 首音频延迟，ASR 和检索不是主要瓶颈。

### 4. 安全增强是否有量化结果

有。安全门控评测结果：

```text
results/safety_gate_eval_summary.json
```

核心结果：

- 总样本：55。
- 标签准确率：1.0。
- 决策准确率：1.0。
- false allow：0。
- false block：0。
- 覆盖类别：off_domain、unsafe、prompt_injection、domain_safe、boundary。

### 5. 是否能持续维护知识库

能。管理后台支持：

- 搜索知识条目。
- 按 tag 和 status 过滤。
- 新增、编辑、删除知识。
- 记录知识版本历史。
- 保存后自动重建索引。

对应接口：

- `GET /api/admin/knowledge`
- `POST /api/admin/knowledge`
- `PUT /api/admin/knowledge/{record_id}`
- `DELETE /api/admin/knowledge/{record_id}`
- `POST /api/admin/reindex`

### 6. 是否有运行复盘闭环

有。每次问答运行会进入审计记录，并可在后台形成 case ledger：

- 自动推断 case 状态。
- 支持 open、investigating、resolved、accepted_risk、ignored。
- 支持 low、medium、high、critical 严重度。
- 支持 latency、safety_gate、quality、asr、llm、tts 等问题类型。
- 支持 owner、reviewer、note。
- 支持导出 CSV / JSONL。

对应接口：

- `GET /api/admin/runs`
- `GET /api/admin/runs/export`
- `PUT /api/admin/runs/{run_id}/case`

## 答辩时推荐说法

我们做的不是一个单纯的网页，而是一套面向船厂安全作业的语音问答系统。用户侧可以进行语音或文本问答，系统内部经过 ASR、术语后处理、安全门控、RAG 检索、LLM 回答和 TTS 合成。管理侧可以维护知识库、查看 provider 健康状态、运行评测任务、复盘每次问答记录。我们同时保留 mock 模式保证现场演示稳定，也支持真实 ASR / LLM / TTS provider 接入，并已经在远程 GPU 环境跑通过真实语音链路。

## 当前仍应如实说明的边界

- 真实端到端语音链路目前是 smoke test 级别，不是大规模生产压测。
- TTS 首音频延迟仍偏高，比赛级版本应优先优化流式 TTS 或换更快的中文语音后端。
- 当前数据库是 SQLite，适合课程项目和单机演示；企业级部署应换 PostgreSQL。
- 当前后台认证是单管理员 token 模式；企业级部署应增加用户、角色和审计权限。
- 当前知识库有版本管理，但还没有严格的审批流和来源可信度评分。

## 下一阶段提分方向

1. 扩大真实链路评测：至少 30 条真实录音跑完整 ASR -> RAG -> LLM -> TTS。
2. 优化 TTS：优先把首音频延迟从 15 秒级降到 3 秒以内。
3. 加强证据引用：回答中明确展示引用的知识条目 ID、标题和风险等级。
4. 增加演示剧本：准备 5 个正常问题、3 个危险问题、2 个 prompt injection 问题、2 个多轮问题。
5. 企业级升级：PostgreSQL、RBAC、服务拆分、异步队列、监控面板。
