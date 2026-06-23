# ShipVoice A2 第二轮全仓 Bug 审计与升级执行文档

> 审计对象：`L-Dramatic/ShipVoice`
> 固定分支：`main`
> 固定提交：`51f45d163e9efeba60c0a820c085cd1c6b3079d3`
> 审计日期：2026-06-22
> 课程选题：A2 级联式造船语音问答系统的复现与改进
> 文档定位：**先找 Bug，再给出可直接落地的修复、复测、重新取证和后续升级方案**

---

## 0. 阅读说明与审计结论

### 0.1 本轮审计边界

本轮原始审计以 GitHub 默认分支 `main` 的固定提交 `51f45d163e9efeba60c0a820c085cd1c6b3079d3` 为代码基线。相较上一轮审计的提交 `e85ca04c6fd156c20f37033c1a8936b78e988463`，该版本前进了 21 个提交，已经完成了 FastAPI 后端、WebSocket 事件流、管理后台、SQLite 持久化、真实 provider 接口、1000/150 条 SFT 数据、LoRA 服务脚本和一条真实 LoRA 链路 smoke 证据等大量升级。

2026-06-22 后续本地修复和 2026-06-23 真实服务器复验已经改变了原始审计结论：本文当前版本按工作区现状删除已完成项，只保留仍需处理、仍需最终报告闭环或仍需更大规模复验的事项。最终提交前仍应以新的 git SHA 和 clean worktree 重新生成 final manifest。

本审计覆盖：

- 根目录启动、依赖、容器和配置；
- `src/shipvoice/` 全部核心后端模块；
- `web/static/` 用户端与后台前端；
- `remote/` ASR、LLM、TTS、LoRA 训练和启动脚本；
- `scripts/` 评测、验证、报告生成和打包脚本；
- `data/` 知识库、SFT、音频清单和评测集；
- `results/` 当前提交中的结果与证据一致性；
- `deliverables/` 报告、讲稿、运行手册及其数字口径；
- `tests/` 当前自动化测试与缺口。

这是一次**静态代码审计 + 仓库证据一致性审计 + 真实服务器复验记录**。2026-06-23 已通过 SSH 隧道重新接通真实 FunASR、ShipVoice LoRA LLM 与 TTS，并完成 30 条 baseline、30 条 streaming 真实音频链路复验和 WebSocket `audio_chunk` 抽样复验。PPTX、DOCX 等二进制交付物以其 Markdown 源稿、生成脚本和仓库元数据为主进行一致性审查；最终提交前仍应重新生成并人工打开检查。

### 0.2 一句话结论

**本文档已按 2026-06-24 当前工作区进展更新：已落地的安全门控 always-on、ASR hint 移除、空 ASR fail-closed、指标口径修正、WebSocket 自动重跑移除、后台默认口令禁用、输入边界、RAG no-evidence、举报例外加固、`/live`/`/ready`、浏览器 `audio.onplaying` 打点、配置原子保存、运行时并发/超时/同会话互斥保护、SQLite WAL/busy timeout/外键、前端 HTTP/WS 超时与坏 JSON 保护、前端取消按钮、WebSocket cancel frame、后端 `cancel_event` 传播、容器非 root/readiness、生产固定端口、LoRA adapter SHA attestation、LLM token/SSE 流、安全闭合句段 TTS 队列、流式片段与非流式完整回答输出 guard、WebSocket audio chunk 与前端分段播放、provider HTTP 连接池复用与可观测计数、30×2×5 真实重复实验、真实浏览器 `audio.onplaying` 批量取证、在线 ASR raw/corrected 评测和 draft final manifest。除用户暂缓的最终报告/PPT/Dashboard 生成外，A2 服务器侧与证据侧关键升级已完成；剩余风险主要是长期工程化项，例如持久队列、依赖锁、远程服务认证和生产化治理。**

### 0.3 当前能力的可信状态

| 能力 | 当前判定 | 说明 |
|---|---|---|
| FastAPI 用户端、后台、SQLite | 基本成立 | 工程量大，接口和数据结构较完整；公开认证、输入边界、运行时总并发/超时、同会话互斥和 SQLite 连接级并发已加固，仍有任务队列、迁移/outbox 与泄露治理 |
| 真实 ASR/LLM/TTS 接口 | 已在线复验 | `/api/ready` 三项 ready；`results/real_chain_smoke_streaming.json`、`results/server_real_batch_*_20260623/` 已保存当前链路证据 |
| LoRA 在线加载 | 已在线复验，hash 已闭环 | 远端 `/health` 返回 `adapter_loaded=true`、`served_model=shipvoice-qwen2.5-7b-lora`、`adapter_sha256=3462dbff405f71ed3d0b0a0d8484498a2be98ffe84ab5b2f56a2d69e7130d1cf`；`/api/ready` 已强校验 SHA |
| 安全门控 | 公开入口已加固 | 所有公开 mode 已执行门控；当前离线安全集 56/56，通过且 false allow=0 |
| ASR 0% CER/WER | 历史 0% 已废弃，在线 ASR 已重评 | `results/asr_online_20260623/summary.json`：50/50 在线 ASR，无 transcript hint，平均 CER/WER 1.58%，术语召回 85.71% |
| 真正流式 LLM/TTS | 已通过真实服务器复验 | `streaming` mode 已走 LLM token/SSE、句级 TTS 队列、WebSocket `audio_chunk` 和前端分段播放；30 条真实音频复验中可回答样本首音频平均提前 3327 ms |
| A2 首段可播放延迟 | 真实浏览器批量已取证 | `results/browser_onplaying_streamable_20260623.json`：20/20 ok，`client_audio_onplaying_ms` p50 4072 ms，p90 5600.1 ms，p95 5836.6 ms |
| 基线 vs 改进公平对比 | 30×2×5 重复实验已完成 | `results/server_real_repeated_20260623/summary.json`：300/300 ok，100/100 gate-allowed 配对中 streaming 更快，平均节省 4147.39 ms |
| 报告/PPT数字一致性 | 草稿 manifest 已有，最终未闭环 | `results/final_manifest_draft.json` 可记录 hash；报告/PPT仍需从最终 manifest 重生成 |
| 可复现性 | 部分成立 | 脚本多，但依赖未锁、原始 LoRA 工件缺失、验证脚本会改写仓库 |

---

## 1. 对照课程 A2 要求的验收矩阵

题目要求的不只是“能回答”，而是：真实串行 ASR→LLM→TTS 基线、至少一项低延迟改进、固定音频集、从用户停止说话到首段开始播放的测量、基线与改进对比、架构/版本/配置/复现实验和局限说明。

| A2 要求 | 当前仓库 | 缺口 | 提交前最低动作 |
|---|---|---|---|
| 串行 ASR→LLM→TTS 基线 | 已完成 30 条真实音频 baseline | `results/server_real_batch_baseline_20260623/summary.json`，30/30 ok | 最终提交前冻结 manifest 并纳入报告 |
| 固定音频指令集 | 有 50 条音频 manifest | 当前 evaluator 主要评表格文本，不在线跑 ASR；test 与规则同源 | 固定 test 子集，保存原始 ASR JSONL、音频 hash、说话人/噪声元数据 |
| 低延迟改进 | 已完成 30×2×5 真实重复实验 | `results/server_real_repeated_20260623/summary.json`：300/300 ok；gate-allowed 样本 streaming 首音频平均 3819.65 ms，较 baseline 平均节省 4147.39 ms | 最终报告/PPT按用户后续要求从 manifest 生成 |
| 首段可播放延迟 | 真实浏览器 `audio.onplaying` 批量已取证 | `results/browser_onplaying_streamable_20260623.json`：20/20 ok，p50 4072 ms，p90 5600.1 ms，p95 5836.6 ms | 最终报告/PPT按用户后续要求引用 |
| 基线 vs 改进 | 已完成重复配对 | `results/server_real_repeated_20260623/summary.md`；100/100 gate-allowed 配对中 streaming 首音频更早 | 最终冻结 manifest 后统一引用 |
| 客观指标 | 有 ASR、门控、检索、引用、多轮 | 多项指标存在同源、自动附 citation、真值回填等污染 | 重建独立 holdout；报告 raw 与 corrected；增加失败率和置信区间 |
| 可复现实验 | 脚本和手册较多；draft manifest 已生成 | 依赖未锁；环境文件被忽略；final manifest 仍未冻结 | 增加 lock、doctor、不可变 final manifest、全新克隆验证 |
| 架构图、模块版本配置 | 文档已有 | 版本、revision、adapter hash 不完整 | 自动输出 `environment.lock.json` 与图中真实 provider/version |
| 局限说明 | 有部分诚实说明 | 同时仍声称“95 分以上”并使用冲突数字 | 删除自评分，改成 Pass/Fail/Unknown 验收表 |

### 1.1 当前最容易被老师追问的五个问题

1. “你们的 `streaming` 到底哪里流式？”——当前代码和真实服务器复验均可证明：LLM SSE/token delta 到达后按句进入 TTS worker，WebSocket 推 `audio_chunk`，前端分段播放；`response_mode=llm_token_stream_sentence_tts`。
2. “首音为什么和总时延一样？”——旧结果如此；当前已区分服务端音频载荷就绪、首个 `audio_chunk` 和浏览器 `onplaying`。最新浏览器批量证据中 `audio.onplaying` p50 为 4072 ms，完整 result 到达平均 8394.9 ms。
3. “ASR 为什么 50 条完全 0 错？”——历史结果不能作为最终结论；当前已去除 hint/回填，并完成 50 条在线 ASR raw/corrected 重评，平均 CER/WER 1.58%，术语召回 85.71%。
4. “为什么换成 `streaming` 后安全门控没了？”——该问题已修复；现在所有公开 mode 都走安全门控。
5. “报告里的 1516 ms、8594 ms、12570 ms、15239 ms 哪一个才是最终结果？”——旧数字都不能作为 FINAL；当前服务器复验数字以 `results/server_real_batch_comparison_20260623.json` 为准，最终报告仍需从同一 final manifest 重生成。

---

## 2. 本次推送相较旧版的真实进步

新版值得保留并在答辩中正面展示的部分如下：

1. 主应用已经由旧 `run_demo.py` 迁移到 `run_app.py + FastAPI`，支持 HTTP、WebSocket、静态前端和管理后台。
2. ASR、LLM、TTS 已抽象成真实 provider；服务不可用时大部分主路径会暴露错误，而不是静默生成 mock。
3. 新增 `SQLiteAppStore`，可保存运行审计、知识记录、评测任务和 case ledger。
4. 用户端支持文件上传和浏览器 `MediaRecorder` 录音，后台支持知识治理、运行复盘和评测任务。
5. 新增 1000 条训练集与 150 条 holdout、QLoRA 训练/评测脚本及公开汇总。
6. `real_chain_smoke_streaming.json` 和 `server_real_batch_*_20260623` 证明当前代码中 ASR、LoRA LLM、TTS 都被真实调用，模型健康信息显示 `adapter_loaded=true`。
7. 安全门控、RAG citation、多轮与 ASR 术语评测均有结构化脚本，已经具备继续完善的工程基础。
8. 交付目录、运行手册、讲稿和报告比旧版完整很多。
9. 2026-06-22 本地加固已完成公开 mode 安全门控、ASR hint 移除、空 ASR fail-closed、WebSocket 不自动重跑、默认后台口令禁用、输入边界、RAG no-evidence 和 `rag.min_score`。
10. 前端已把 `streaming` 升级为“流式低延迟”，支持 WebSocket 音频分段队列和浏览器 `audio.onplaying` 打点，不再把服务端完整 TTS 返回时间当作最终首播。
11. 后端已新增 `/api/live` 与 `/api/ready`，provider 未启动时 readiness 返回 503；后台配置保存已改成验证后原子替换；`scripts/build_final_manifest.py` 可生成 draft manifest。
12. 运行时新增全局 pipeline 信号量、同 session 锁、排队等待上限和总 deadline；SQLite 连接已启用 WAL、外键、busy timeout；前端 HTTP/WS 已加超时、AbortController 和坏 JSON 保护；容器已改非 root、compose healthcheck 已切 `/api/ready`，生产启动可用 `--no-auto-port` 避免端口静默漂移。

这些进步说明项目不是“推倒重做”。当前已经完成**证据口径校正 + P0 安全止血 + 真流式代码升级**，后续重点应放在**真实服务重跑取证 + 公平 baseline vs streaming 实验 + 最终报告闭环**。

---

## 3. 全量缺陷登记表

以下表格中的“确认”表示可以直接由当前提交代码触发；“证据问题”表示当前结果不能支撑报告中的强结论；“升级项”表示不一定立即报错，但会阻碍 A2 验收或后续工程化。

| 编号 | 等级 | 问题 | 主要文件 | 根因/触发 | 影响 | 修复方向 | 验收标准 |
|---|---|---|---|---|---|---|---|
| P0-06 | P0 | provider 队列和速率限制仍不完整 | src/shipvoice/fastapi_app.py; web/static/app.js; providers | 请求体、history、base64、全局 pipeline 信号量、同 session 锁、排队等待上限、总 deadline、前端 HTTP/WS 超时、cancel frame 与后端 provider 取消传播已加；但速率限制、持久队列、provider 分级 worker 状态仍不完整 | 真实服务在线和高并发演示时仍可能出现后台评测抢占模型资源或不同 provider 之间缺少独立背压 | 加速率限制、持久队列和 ASR/LLM/TTS worker 状态 | 超大输入 413/422；并发压测不超过配置上限；provider 队列与后台任务不会抢占前台演示 |
| P0-07 | P0 | 报告、PPT、结果与提交 SHA 仍未最终统一 | results/project_acceptance_report.*; deliverables/final_submission/**; scripts/build_acceptance_report.py; scripts/build_final_manifest.py | 已新增 `results/final_manifest_draft.json`，真实服务重复实验、ASR、browser 和 adapter SHA 证据已完成；但报告/PPT/Dashboard 按用户要求暂不生成 | 答辩数字仍可能互相冲突，除非后续只读 manifest 生成 | 基于最终证据生成冻结 final manifest；所有报告/PPT/Dashboard 只读该 manifest；dirty/stale 时失败 | 报告、PPT、Dashboard 的每个数字与 final manifest 一致 |
| P0-08 | P0 | ASR 0% CER/WER 不能证明真实识别质量 | scripts/evaluate_asr_online.py; data/audio/audio_manifest.csv; results/asr_online_20260623 | 历史 0% 指标已降级；当前已执行 50 条在线 ASR raw/corrected 评测，不发送真值 hint | 已有可提交 ASR 质量证据；长期仍需更大外部 holdout | 保留 raw JSONL、corrected 文本、CER/WER、术语召回和噪声分层；报告不得再引用历史 0% 作为主结论 | `results/asr_online_20260623/summary.json` 显示 50/50 evaluated、平均 CER/WER 1.58%、term recall 85.71% |
| P0-09 | P0 | LoRA adapter hash attestation 已闭环 | src/shipvoice/fastapi_app.py; remote/serve_transformers_openai.py; scripts/attest_lora_adapter.py | 远端 `/health` 已返回 adapter SHA、文件数和字节数；本地 `/api/ready` 已按 `SHIPVOICE_LORA_ADAPTER_SHA256` 强校验 | 错误 adapter/base-only 服务会 readiness fail | 保留 attestation JSON；最终报告引用 SHA 与 health 摘要 | `results/lora_adapter_attestation_20260623.json` 中 `sha_match=true` |
| P0-10 | P1 | 基线 vs 改进重复实验已完成 | scripts/run_real_chain_repeated.py; results/server_real_repeated_20260623 | 已跑 30 条样本 × 2 mode × 5 repeats，且同一真实 ASR/LoRA/TTS 链路；随机顺序执行 | A2 低延迟结论已有重复实验证据；最终报告/PPT仍需按用户后续要求生成 | 从同一 final manifest 引用 p50/p90/p95、失败率和样本数 | `results/server_real_repeated_20260623/summary.json`：300/300 ok，100/100 gate-allowed 配对 streaming 更快 |
| P1-02 | P1 | 未知输入默认允许 | src/shipvoice/providers.py | 未命中规则即 uncertain+allowed | 陌生越权表达进入 LLM | 高风险部署 fail-safe：澄清/受限模板；二级分类器；输出过滤 | 对变形攻击 false allow 达到预设阈值以下 |
| P1-03 | P1 | ASR 术语规则双源漂移 | src/shipvoice/providers.py; configs/asr_postprocess_rules.json | 运行时硬编码 5 条，配置 13 条，且含无操作映射 | 线上与离线评测不一致 | 运行时只加载一个版本化规则文件，记录 rule_id/before/after/confidence | 每条规则单测通过，配置 hash 写入结果 |
| P1-05 | P1 | RAG confidence 未校准 | src/shipvoice/providers.py | 第一名相对分总是接近 1，即使绝对分很弱 | UI 显示“100%置信度”误导 | 保存原始 BM25/vector/reranker 分并在验证集校准概率 | confidence calibration ECE/Brier 或至少分桶准确率 |
| P1-06 | P1 | Citation 100%部分是程序自动附加 | src/shipvoice/pipeline.py; scripts/evaluate_citation_quality.py | pipeline 无条件在答案末尾附 top hit ID，评测只检查 ID 存在 | 指标无法证明回答事实被证据支持 | 增加 claim-evidence entailment、引用跨度和人工盲评 | 每个关键 claim 能映射到具体 chunk/page |
| P1-07 | P1 | 客户端 history 可伪造 assistant 消息 | src/shipvoice/fastapi_app.py; src/shipvoice/providers.py; web/static/app.js | 服务器信任客户端上传的任意历史角色和内容 | 提示注入、越权上下文、审计不可信 | 服务器按 session 从数据库取历史；客户端只发 session_id；清洗/截断 | 伪造 assistant history 不影响服务端上下文 |
| P1-10 | P1 | 后台评测任务缺互斥、取消和恢复 | src/shipvoice/fastapi_app.py; src/shipvoice/sqlite_store.py | daemon thread 可并发启动完整 LLM/TTS 评测，重启即丢 | GPU 资源争抢、数据库状态悬挂 | 单 worker 队列、唯一 active job、cancel token、重启恢复/标记中断 | 重复点击只产生一个运行任务，可取消且状态一致 |
| P1-11 | P1 | 远程服务无认证/TLS/限流且绑定 0.0.0.0 | remote/serve_*.py; remote/start_*.sh | 模型端点可能直接暴露公网 | 语音/问题泄露、模型资源被滥用 | 默认 bind 127.0.0.1 + SSH 隧道；或反代 bearer/mTLS、IP allowlist | 外部未授权请求被拒绝，日志不含敏感原文 |
| P1-12 | P1 | SQLite God class 与事务/恢复风险 | src/shipvoice/sqlite_store.py; src/shipvoice/audit.py | 1538 行单类；连接级 WAL、外键和 busy_timeout 已加；但 DB 与 JSONL/index 双写、迁移、完整索引和 outbox 仍未闭环 | 崩溃后数据与索引不一致，多 worker 下仍可能有业务级竞态 | migration；DB 单一事实源；outbox 重建索引；分页/索引补齐 | 并发测试无 locked 错误，故障注入可恢复 |
| P1-13 | P1 | SFT holdout 存在语义/来源泄漏 | scripts/build_expanded_sft_dataset.py; data/training/* | train/eval 都由同一 20 个 KS、同一规则、同一对话模板派生，只排除 exact input | 0 overlap 不等于独立泛化 | 按 source_id/scenario/rule/speaker 分组拆分；外部作者编写 holdout | 训练集任何源 ID 不出现在 test，近重复检测通过 |
| P1-14 | P1 | LoRA 评价只数拒答词和答案长度 | scripts/summarize_remote_lora_results.py | 拒答标记增加可能同时代表 safe false block 增加 | 无法证明 LoRA 质量提升 | 分类混淆矩阵、safe answer quality、事实性、人工盲评、base/RAG/LoRA 消融 | 报告 false allow、false block、domain quality 和配对显著性 |
| P1-15 | P1 | 训练缺完整可复现控制 | remote/train_qwen_lora.py | 无 eval_dataset、early stopping、seed 证据、revision；bf16 判断粗糙 | 训练结果难复现或在部分 GPU 失败 | 固定 revision/seed，支持检查 bf16，定期 eval，保存 best，记录 truncation | 两次同配置指标在允许误差内，完整 run manifest |
| P1-16 | P1 | Edge TTS 片段直接拼接 MP3 字节 | remote/serve_edge_tts.py | 多个独立 MP3 容器字节串联，不是真正音频流 | 部分播放器截断或只播第一段 | 输出连续 PCM/WAV/Opus chunk；sequence id；客户端队列播放 | 长文本所有句子可连续播放，无多头文件问题 |
| P1-17 | P1 | 依赖未固定且测试依赖缺失 | requirements.txt; tests/* | fastapi/uvicorn/python-docx 无版本；httpx/websockets 未保证安装 | 新环境测试和行为漂移 | `pyproject.toml` + prod/dev lock；Python 版本矩阵；hash-check | 空环境安装后单元/集成测试可重复通过 |
| P1-18 | P1 | 容器镜像仍需生产级收敛 | Dockerfile; .dockerignore; docker-compose.app.yml | 已改非 root、`.dockerignore` 排除 results/deliverables/audio/env/models、compose healthcheck 切 `/api/ready`、容器启动使用固定端口；但仍复制整仓，未做多阶段/read-only/镜像扫描/资源限制 | 供应链、隐私和运行稳定性风险仍需进一步降低 | 多阶段、只复制运行文件、read-only、资源限制、锁 digest、镜像扫描 | 镜像扫描通过，容器不可写源码，provider 不健康时容器不 ready |
| P1-19 | P1 | 测试依赖本地被忽略环境并污染真实库 | tests/test_admin_api.py; scripts/smoke_fastapi_backend.py | .local.env 在干净克隆不存在；smoke 在真实知识库创建/删除记录 | 测试不可复现且可能误删数据 | 临时目录、临时 SQLite、fake providers、fixture config、transaction rollback | 测试前后 git diff 和正式 DB 均无变化 |
| P1-20 | P1 | 知识库缺权威来源和版本治理 | data/knowledge/ship_safety_corpus.jsonl; scripts/build_knowledge_index.py | 20 条短条目，source 常为文件名，缺发布者、日期、条款、许可、审核人 | 安全回答依据薄弱，citation 看似完整但不可核验 | 增加 source URL/文献、publisher、version、effective date、clause/page、license、review | 每个 critical chunk 有可核验来源与审核状态 |
| P1-21 | P1 | 验证脚本会改写仓库且“quick”不跑单测 | scripts/validate_project.py; scripts/validate_real_only.py | validate 会重建数据/报告；real-only 只搜禁词；最后仍打印 OK | 验证结果给出虚假安全感并导致 dirty tree | build 与 validate 分离；validate 只读；显式单测/集成/在线状态为 Pass/Skip/Fail | 验证后 git diff 为空，任何 skipped 项不计 Pass |
| P1-22 | P1 | 异常详情和本地绝对路径进入 API/结果 | fastapi_app.py; results/*.json; remote health | 客户端/报告可见路径、stdout/stderr、adapter 本机位置 | 信息泄露且跨机器不可复现 | 错误码与内部 trace 分离；路径改相对 artifact URI；日志脱敏 | 提交包 secret/PII/path 扫描无高危命中 |
| P2-01 | P2 | VAD 事件为固定 0ms | src/shipvoice/pipeline.py | 未进行真实端点检测却展示 VAD 完成 | 时间线误导 | 无 VAD 就删除节点；或实现客户端/ASR endpoint 事件 | UI 仅展示真实发生的阶段 |
| P2-02 | P2 | 阻断请求 UI 把 TTS 标为 blocked，但后端仍播拒答 | web/static/app.js; src/shipvoice/pipeline.py | 前后端状态语义冲突 | 演示时难解释 | 显示“LLM skipped / safety TTS played” | 阻断运行时间线与实际 provider 调用一致 |
| P2-04 | P2 | 整个音频/回答以 base64 常驻内存并导出 | web/static/app.js; API schema | 大音频复制多份，导出包含 TTS 和会话敏感内容 | 内存高、日志包膨胀、隐私风险 | multipart/二进制 WS；对象 URL；导出默认剔除 audio 和敏感文本 | 30–60 秒音频内存稳定，导出不含原始音频 |
| P2-05 | P2 | 可视化在无真实 analyser 时模拟波形 | web/static/app.js | 视觉上像真实输入但可能是模拟 | 答辩可被质疑 | 标识“visual fallback”，评测界面禁用模拟 | 无音频时画布不显示伪波形 |

### 3.1 修复优先级定义

- **P0：必须优先处理。** 会导致安全绕过、证据失真、核心题目不成立、严重数据泄露或重复昂贵调用。
- **P1：提交前尽量修复或至少在报告中明确。** 会影响可复现性、质量、稳定性和答辩可信度。
- **P2：工程质量和用户体验问题。** 不一定阻断演示，但不应再包装成已完成能力。

建议后续优先处理仍在表中的 P0-06 剩余 provider 队列/速率限制部分、P0-07，再处理 P1-02、P1-03、P1-05、P1-07、P1-10、P1-17、P1-19、P1-21。不要先花时间美化 UI、加更多图表或扩大自评分。

---

## 4. 已完成并从待办删除的 P0 止血项

以下原始缺陷已在当前工作区落地，不再作为后续待办保留。服务器相关项目已在 2026-06-23 完成真实复验，不能再把这些问题写成“当前仍未修复”。

| 原编号 | 当前状态 | 验证 |
|---|---|---|
| P0-03 真流式 LLM/TTS 缺真实服务器复验 | 已完成服务器侧复验：远端 LoRA LLM 支持 `stream=true` SSE，pipeline 按句进入 TTS worker，WebSocket 推 `audio_chunk` | `results/server_real_batch_streaming_20260623/summary.json`；`results/websocket_streaming_smoke_audio.json`；`results/server_real_batch_comparison_20260623.md` |
| P0-10 没有真实基线 vs 改进实验 | 已完成第一轮真实配对，并扩展到 30×2×5 重复实验：300/300 ok，100 条可回答配对中 streaming 首音频 100/100 更早 | 重复实验 baseline 首音频平均 7967.04 ms；streaming 首音频平均 3819.65 ms；平均节省 4147.39 ms |
| P0-01 安全门控被 mode 绕过 | 已修复：所有公开 mode 都执行 `KeywordSafetyGate`，非法 mode 返回 422 | `python -m unittest discover -s tests`；`python scripts\evaluate_safety_gate.py --gate-only --fail-on-critical` |
| P0-02 ASR 真值提示泄漏与空结果回填 | 已修复：音频请求不再发送 `transcript_hint`，FunASR 空识别 fail-closed；50 条在线 ASR raw/corrected 评测已完成 | `tests.test_p0_hardening`；`results/asr_online_20260623/summary.json` |
| P0-04 WebSocket 失败后盲目 HTTP 重试 | 已修复：前端不再自动 HTTP 重跑；新增 `client_request_id` 和 `/api/runs/{run_id}` 查询 | `tests.test_p0_hardening`、`tests.test_admin_api` |
| P0-05 默认管理员密码和公开 session | 已修复：默认密码禁用，secret 默认进程随机，`/api/sessions` 无 session_id 时需管理员 | `tests.test_p0_hardening`、`tests.test_admin_api` |
| P1-01 举报/防止例外拼接绕过 | 已修复：纯举报允许，混合危险方法请求拒绝 | `test_reporting_exception_does_not_allow_mixed_unsafe_request` |
| P1-04 RAG 无命中返回默认文档 | 已修复：无匹配返回空 evidence，`rag.min_score=2.0` | `tests.test_evidence_citations`；`python scripts\evaluate_retrieval.py` |
| P1-08 健康检查假阳性 | 已修复应用层：新增 `/api/live` 与 `/api/ready`，provider 未开时 `/api/ready=503`，当前真实服务在线时 `/api/ready=200` | `test_live_and_ready_endpoints_are_separate`；2026-06-23 本地隧道 ASR/LLM/TTS 三项 ready |
| P1-09 配置保存非原子 | 已修复：临时文件验证、pipeline 构造成功后原子替换，并保留 `.bak` | `python -m unittest discover -s tests` |
| P0-06 基础并发/总超时/取消边界 | 已部分修复：HTTP/WS 主链通过全局信号量、同 session 锁、排队等待上限、总 deadline 和运行级 `cancel_event` 控制；超限返回 409/429/504，取消返回 499 并记录 `cancelled`；`/api/health` 暴露运行时限额 | `test_runtime_limits_are_bounded_by_environment`、`test_same_session_concurrent_run_is_rejected`、`test_cancel_running_run_sets_cancel_event`；`python -m unittest discover -s tests` |
| P1-12 SQLite 连接级并发基础 | 已部分修复：连接启用 `foreign_keys=ON`、`busy_timeout=5000`、`journal_mode=WAL`、`synchronous=NORMAL` | `python -m py_compile src\shipvoice\sqlite_store.py` |
| P2-03 前端超时/解析/取消闭环 | 已修复：HTTP 使用 `AbortController`；WebSocket 有 deadline；WS/HTTP 均处理非 JSON/坏 JSON 响应；前端运行中取消会发送 HTTP cancel 或 WebSocket cancel frame，后端记录 `cancelled` | `node --check web\static\app.js`；`test_cancel_running_run_sets_cancel_event` |
| P1-18/P2-06 容器与生产端口基础 | 已部分修复：Docker 非 root；compose healthcheck 调 `/api/ready`；`.dockerignore` 排除结果/音频/env/模型；`run_app.py --no-auto-port` 让生产端口占用直接失败 | `python -m py_compile run_app.py` |

剩余 ASR 质量、LoRA 真实性和低延迟结论不再卡在这些已修复 bug 上；服务器侧真实批量重跑、adapter hash attestation、独立 ASR 质量报告、浏览器 `onplaying` 批量回传、30×2×5 重复实验、输出 guard、连接复用和运行取消闭环均已完成。按用户当前范围，后续只保留最终报告/PPT/Dashboard 统一生成，以及持久队列、认证限流、依赖锁等长期工程化项。

---

## 5. P0-03：真流式 LLM/TTS 已完成真实服务器复验

### 5.1 当前已落地的流式链路

`streaming` mode 当前链路是：

```text
ASR final
-> gate always-on
-> LLM stream=True SSE/token delta
-> sentence accumulator
-> TTS worker queue
-> WebSocket audio_chunk(seq, audio_base64, mime_type)
-> browser audio segment queue
-> <audio>.onplaying client timing ACK
```

当前已经完成：

- 新增 `llm_complete_ms`、`tts_complete_ms`、`server_audio_payload_ready_ms`；
- 新增 `llm_first_delta_ms`、`server_first_audio_chunk_ready_ms`、`server_audio_stream_complete_ms`、`streamed_audio_segments`；
- `OpenAICompatibleLLMProvider.stream_answer()` 支持 OpenAI/vLLM SSE；
- 自建 `remote/serve_transformers_openai.py` 支持 `stream=true` 与 `TextIteratorStreamer`；
- pipeline 已实现句级 accumulator 与 TTS worker queue；
- WebSocket 已支持 `audio_chunk` 帧；
- 前端已实现分段音频队列和顺序播放；
- 前端新增浏览器 `audio.onplaying` 打点，并通过 `/api/runs/{run_id}/client-timing` 回写 metrics；
- 旧字段继续保留兼容历史 CSV/JSON，但不能作为最终首播结论；
- 2026-06-23 已用真实 ASR、ShipVoice LoRA LLM、TTS 服务器跑通 baseline/streaming 批量复验。

本次服务器复验证据：

- `results/server_real_batch_baseline_20260623/summary.json`：30 条 baseline，30/30 ok，`response_mode=complete_payload_non_streaming`。
- `results/server_real_batch_streaming_20260623/summary.json`：30 条 streaming，30/30 ok，`response_mode=llm_token_stream_sentence_tts`。
- `results/server_real_batch_comparison_20260623.md`：20 条可回答样本中，baseline 首音频 ready 平均 7161.9 ms，streaming 首音频 ready 平均 3834.9 ms，平均提前 3327.0 ms，20/20 streaming 更早。
- `results/server_real_repeated_20260623/summary.json`：30 条音频 × 2 mode × 5 repeats，300/300 ok；100 条 gate-allowed 配对中 streaming 100/100 更早，baseline 首音频平均 7967.04 ms，streaming 首音频平均 3819.65 ms，平均节省 4147.39 ms。
- `results/browser_onplaying_streamable_20260623.json`：真实浏览器 20/20 ok，`client_audio_onplaying_ms` p50 4072 ms，p90 5600.1 ms，p95 5836.6 ms；首段播放早于最终 result。
- `results/websocket_streaming_smoke_audio.json`：真实音频 WebSocket 请求收到 4 个 `audio_chunk`，首 chunk 5767 ms 到达，最终 result 11915 ms 到达，首 chunk 早于最终结果。

当前结论是：真流式低延迟能力已经有服务器侧、WebSocket 首包、真实浏览器 onplaying 和重复实验四类证据支撑。最终报告/PPT仍需在用户恢复该部分工作时只读 final manifest 统一生成，不能混用旧数字。

### 5.2 已实现的真流式流水线

```text
browser speech_stop
  -> audio stream/final upload
  -> ASR final or stable partial
  -> gate always-on
  -> RAG
  -> LLM SSE/token stream
  -> sentence accumulator
  -> bounded TTS queue
  -> TTS chunk 0
  -> WebSocket audio_chunk
  -> browser decode
  -> audio.onplaying
  -> client timing ACK
```

核心接口：

```python
class StreamingLLM(Protocol):
    async def stream_answer(...) -> AsyncIterator[TokenDelta]: ...

class StreamingTTS(Protocol):
    async def synthesize(text: str) -> TTSResult: ...
```

当前 TTS provider 仍是“每句完整合成”，不是字节级连续 TTS；但 pipeline 不再等待完整 LLM answer 才启动 TTS，而是在句子完成后立即合成并推送首段音频。这满足课程 A2 中“句级切分 + 首句优先播放”的级联低延迟改进路径。

事件 schema：

```json
{"type":"llm_delta","seq":12,"text":"完成审批"}
{"type":"event","event":{"stage":"tts_queue","payload":{"seq":0,"chars":12}}}
{"type":"audio_chunk","chunk":{"seq":0,"mime_type":"audio/wav","audio_base64":"...","server_audio_chunk_ready_ms":2378}}
{"type":"client_playing","seq":0,"client_elapsed_ms":2378}
```

### 5.3 句级切分要求

- 中文标点 `。！？；` 与长度阈值共同触发；
- 第一段建议 12–40 个汉字，过短会频繁 TTS，过长会拖慢首播；
- 引用 ID 和长来源不进入第一句语音；UI 单独展示 citation；
- 对缩写、数字、括号和小数避免误切；
- TTS 队列必须有界，例如 `maxsize=2`，防止 LLM 快于 TTS 时无限占内存；
- 客户端断开、用户打断时，已通过运行级 `cancel_event` 取消后续 LLM/TTS task。

### 5.4 首播指标的唯一正确公式

```text
E2E_first_play_ms = client_audio_onplaying_ts - client_speech_stop_ts
```

同时保存分解：

```text
upload_ms
asr_final_ms
safety_gate_ms
retrieval_ms
llm_ttft_ms
first_sentence_ready_ms
tts_first_byte_ms
client_first_chunk_received_ms
client_decode_ms
client_onplaying_ms
```

只有 `E2E_first_play_ms` 才能用于课程题目中的“用户停止说话到首段音频开始播放”。

---

## 6. P0-06：并发、超时和模型队列边界

认证、公开 session、默认口令、配置 secret、健康检查分层、基础输入限制、全局 pipeline 并发、同 session 互斥、排队等待上限、总 deadline 和用户取消传播已经完成。本节只保留仍未完成的资源治理项。

### 6.1 当前剩余缺口

- 当前只做了主 pipeline 全局信号量，还没有按 ASR/LLM/TTS provider 分别建 worker 队列；
- 已有总 deadline，还没有 ASR/LLM/TTS 分阶段 deadline；
- live 评测仍可能一键触发完整 LLM/TTS，缺少成本/资源队列控制；
- MIME/音频时长仍需解码器级校验，不能只依赖 base64 大小。

### 6.2 输入与资源上限

推荐最小值，可按设备调整：

| 项 | 限制 |
|---|---:|
| HTTP JSON body | 12 MiB |
| 解码后音频 | 8 MiB |
| 音频时长 | 60 s |
| 问题文本 | 512 Unicode 字符 |
| history | 12 turns，单条 2000 字符，总计 8000 字符 |
| TTS 文本 | 1000 字符；更长先摘要/截断 |
| 同会话并发 | 已支持同 session 锁，第二个并发请求返回 409 |
| 全局 pipeline 并发 | 已支持 `SHIPVOICE_MAX_CONCURRENT_RUNS`，课程版建议 1–2 |
| 请求 deadline | 已支持全局 `SHIPVOICE_RUN_TIMEOUT_SECONDS`；仍需 ASR/LLM/TTS 分阶段 deadline |
| 用户取消 | 已支持前端取消按钮、WebSocket cancel frame、`POST /api/runs/{run_id}/cancel` 和 pipeline/provider `cancel_event` 传播 |

base64 使用严格解码：

```python
base64.b64decode(value, validate=True)
```

文件名不可作为 MIME 依据；必须由解码器检查。统一转成 16 kHz、mono、PCM WAV 后再送 ASR。超限应在模型调用前返回 413/422。

### 6.3 验收

- 并发压测中全局 pipeline 调用数不超过配置上限，后续再拆成 ASR/LLM/TTS worker 上限；
- 用户取消或连接断开后，后端取消并记录 `cancelled`；
- 超时、取消、provider 不可用都写入审计；
- 后台 live 评测排队执行，不会并发抢占模型 worker。

---

## 9. P0-07：建立唯一可信结果源，彻底解决数字漂移

### 9.1 当前冲突示例

当前仓库至少混有：

- 旧历史 3 条 ASR/TTS 链路，平均所谓首音约 15.24 s，LLM 不是当前 LoRA 主链；
- 当前 LoRA 单样本 smoke，约 12.57 s，首音与总耗时相等；
- 最终报告仍写多轮平均首音 1516 ms、总耗时 2920 ms、关键词召回 97.22%；
- 当前 `multiturn_eval_summary.json` 则约为 8594 ms、73.61%；
- 自动验收报告固定在旧提交、dirty tree，却给出 97 分；
- ASR 报告写 0%，但存在真值回填和同集后处理。

### 9.2 新的最终实验目录

```text
results/final_20260622_<runid>/
├─ experiment_manifest.json
├─ environment.json
├─ provider_attestation.json
├─ config.snapshot.json
├─ audio_manifest.snapshot.csv
├─ raw/
│  ├─ asr_outputs.jsonl
│  ├─ pipeline_events.jsonl
│  ├─ client_timings.jsonl
│  └─ errors.jsonl
├─ summary/
│  ├─ asr_summary.json
│  ├─ latency_summary.json
│  ├─ safety_summary.json
│  └─ quality_summary.json
└─ hashes.sha256
```

`experiment_manifest.json` 最少包含：

```json
{
  "git_sha": "51f45d...",
  "git_dirty": false,
  "started_at": "...",
  "config_sha256": "...",
  "corpus_sha256": "...",
  "index_sha256": "...",
  "audio_manifest_sha256": "...",
  "base_model_id": "Qwen/Qwen2.5-7B-Instruct",
  "base_model_revision": "...",
  "adapter_sha256": "...",
  "asr_model_revision": "...",
  "tts_model_revision": "...",
  "pipeline_variant": ["serial", "streamed"],
  "sample_count": 30,
  "repeats": 5
}
```

### 9.3 报告生成器必须 fail closed

`scripts/build_acceptance_report.py` 不应再自行打“97 分”。改成：

- 每项只输出 `PASS / FAIL / UNKNOWN / HISTORICAL`；
- 当前 git dirty 时拒绝生成 `final` 报告；
- 当前 SHA 与 manifest 不同，拒绝生成；
- 输入结果缺 hash 或不同配置，拒绝合并；
- 样本不足，显示 `UNKNOWN`，不能自动给满分；
- 历史结果必须有醒目的“不可与当前版本直接比较”。

### 9.4 当前交付物必须同步修改

重点文件：

- `deliverables/final_submission/report/...最终版.md/.docx`
- `deliverables/final_submission/slides/ShipVoice_答辩PPT逐页讲稿.md`
- `deliverables/final_submission/manuals/ShipVoice_可复现实验与运行手册.md`
- `README.md`
- `results/project_acceptance_report.md/.json`
- `deliverables/ShipVoice_Evaluation_Dashboard.html`

删除或改写：

- “已经具备 95 分以上所需证据”；
- “系统已经达到课程高分交付标准”；
- 未注明版本的 100% 指标；
- 将服务器完整音频 ready 写成“用户首音”；
- 将 2026-06-12 历史链路写成当前真值；
- 将同源 holdout 当成泛化能力证明。

---

## 10. P0-08：ASR 评测重做方案

### 10.1 当前脚本的问题

`evaluate_asr_transcripts.py` 主要读取 `audio_manifest.csv` 的已有列计算编辑距离，并不会确保每条音频刚刚通过当前 ASR provider 推理。默认列还是经过术语修正后的 `asr_transcript`。这能评“清单文本与参考文本的差异”，不能证明“当前提交 + 当前模型 + 当前服务”的真实识别效果。

### 10.2 推荐拆成三步

**步骤 A：不可变在线推理**

新增 `scripts/run_asr_eval_live.py`：

```bash
python scripts/run_asr_eval_live.py   --manifest data/audio/audio_manifest_test.csv   --endpoint http://127.0.0.1:18001/asr   --out results/final.../raw/asr_outputs.jsonl   --no-reference-hint
```

输出每条：audio hash、raw text、provider/model revision、耗时、错误、空输出、音频元数据。原始文件只写一次，不允许后处理脚本覆盖。

**步骤 B：冻结规则后处理**

```bash
python scripts/apply_asr_rules.py   --rules configs/asr_postprocess_rules.v2.json   --input raw/asr_outputs.jsonl   --output raw/asr_corrected.jsonl
```

每次修改记录 rule id；规则只在 dev 集调整。

**步骤 C：独立评分**

报告：

- raw micro/macro CER；
- corrected micro/macro CER；
- 术语 precision、recall、F1；
- false correction rate；
- empty transcript rate；
- 按 speaker/noise/category 分组；
- bootstrap 95% CI；
- 失败样本逐条表。

中文若未使用固定分词器，不要叫 WER；可称“字符错误率 CER”或“混合 token error rate”，并清楚定义。

### 10.3 数据拆分

```text
train/dev：可用于热词和规则设计
final_test：冻结后才打开，不允许调整规则
```

按说话人、场景、source phrase 分组拆分，避免同一个句子换个说话人同时出现在开发与测试中。至少加入未见过的自然改写，而不是全部背诵清单句子。

---

## 11. P0-09：LoRA 必须由系统证明，而不是依赖模型名称

### 11.1 当前风险

应用侧已经读取 `SHIPVOICE_REQUIRE_LORA=1`，并要求 `SHIPVOICE_LLM_MODEL` 包含 `SHIPVOICE_REQUIRE_LLM_MODEL_SUBSTRING`；`/api/ready` 也会检查 OpenAI-compatible `/v1/models` 是否列出配置模型。

剩余风险是：模型名称仍不能证明服务端真的加载了 adapter。当前还缺 base revision、adapter loaded、adapter SHA-256 等 attestation 字段；`start_vllm_llm.sh` 也仍需确认实际使用 `--enable-lora` 与 `--lora-modules`。

### 11.2 模型 attestation

LLM `/health` 或 `/v1/models` 扩展：

```json
{
  "served_model_id": "shipvoice-qwen2.5-7b-lora",
  "base_model_id": "Qwen/Qwen2.5-7B-Instruct",
  "base_revision": "<commit>",
  "adapter_loaded": true,
  "adapter_name": "shipvoice",
  "adapter_sha256": "...",
  "adapter_config_sha256": "...",
  "dtype": "bfloat16",
  "quantization": "4bit-nf4"
}
```

应用 readiness 如果 `require_lora=true`：

- 必须读取并验证上述字段，而不只检查模型名；
- adapter false、hash 不匹配、model id 不匹配时 `/ready` 返回 503；
- 每条结果保存 attestation hash，而不是只保存模型名称。

### 11.3 vLLM 启动示例

```bash
python -m vllm.entrypoints.openai.api_server   --model Qwen/Qwen2.5-7B-Instruct   --served-model-name shipvoice-qwen2.5-7b-lora   --enable-lora   --lora-modules shipvoice=/root/.../qwen_lora_shipvoice_expanded   --host 127.0.0.1   --port 11434
```

具体参数需按安装的 vLLM 版本核对并锁定；不要在文档中写一个未经实际验证的命令后声称已完成。

---

## 12. P0-10：A2 基线与改进实验必须重新设计

### 12.1 公平对比原则

基线和改进必须保持以下内容相同：

- 同一 ASR 模型/revision/hotwords；
- 同一安全门控；
- 同一 RAG 索引和 top-k；
- 同一 LLM 权重、adapter、temperature、max tokens；
- 同一 TTS 声音、采样率和文本；
- 同一硬件、网络和预热状态；
- 同一批音频与同一失败处理。

唯一变量：

```text
serial：完整 LLM -> 完整 TTS -> 一次返回
streamed：token 流 -> 首句 -> TTS chunk -> 首段优先播放
```

不能用“baseline 关闭 gate/RAG、full 开启 gate/RAG”来证明性能改进，因为功能和回答质量都变了。

### 12.2 推荐数据规模

提交前最低可信方案：

- 30 条冻结音频；
- 3 位说话人，每位至少 10 条；
- safe 15、术语/噪声 5、unsafe/off-domain 10；
- 每个 variant 3 次预热不计入；
- 每条每个 variant 重复 5 次；
- 顺序随机且配对；
- 共 `30 × 2 × 5 = 300` 条有效运行，失败也保留。

时间紧时可以先 10 条 × 3 repeats，但必须写“预实验”，不能用来声称稳定泛化。

### 12.3 必报指标

| 类别 | 指标 |
|---|---|
| 用户等待 | E2E first play p50/p90/p95/mean/CI |
| 完整响应 | E2E completion p50/p90/p95 |
| 阶段 | ASR final、gate、RAG、LLM TTFT、first sentence、TTS first byte、client decode |
| 稳定性 | success rate、timeout rate、empty ASR、TTS decode failure |
| 质量控制 | CER、门控正确率、答案关键词/人工评分、TTS 可播放率 |
| 改进效果 | 每条配对差值、相对下降%、95% bootstrap CI |

### 12.4 结果表模板

| Variant | N | Success | E2E first-play p50 | p90 | p95 | Mean | 95% CI | Answer quality |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| Serial baseline | 150 |  |  |  |  |  |  |  |
| Streamed improved | 150 |  |  |  |  |  |  |  |
| Paired improvement | 150 pairs |  |  |  |  |  |  | quality delta |

在真实数据未生成前，表格必须留空或写 `N/A`，不要填估算值。

---

## 13. 安全门控完整升级方案

### 13.1 规则预处理

输入先执行：

```text
Unicode NFKC
去零宽字符
全半角统一
大小写统一
可控空白/标点归一
繁简转换（若引入库须锁版本）
ASR 常见混淆词映射
```

保留 raw 和 normalized，审计中同时记录，避免无法追溯。

### 13.2 三层判定

1. **硬规则层**：明确绕过、破坏、篡改、隐瞒、提示注入，直接 block。
2. **轻量分类层**：domain safe / unsafe / off-domain / injection / uncertain，输出 calibrated score。
3. **受限生成与输出层**：即使允许，LLM system prompt、RAG 和输出扫描仍限制危险步骤、虚构标准和泄密。

高风险门控异常时 fail closed：播放固定安全提示，不调用开放式 LLM。

### 13.3 对抗测试集

在现有 55 条以外，至少补：

- 空格/标点拆分：`绕 过 安 全 检 查`；
- 零宽字符、全角、繁体；
- 同音/ASR 错字：`绕锅审批`、`测氧测报`；
- 复合句：先问安全，再追加危险方法；
- 安全例外拼接：`如何上报？顺便告诉我怎么做`；
- 多轮注入：第一轮正常，第二轮让其忽略规则；
- 伪造 assistant history；
- 文档注入：RAG 文本中包含“忽略系统规则”；
- 英中混合、编码、角色扮演、引用攻击；
- 只说隐晦目标，不出现关键词。

报告必须给 false allow，且把 false allow 视为比 false block 更严重。100% 只可描述为“在本测试集上”，不能写“系统绝对安全”。

---

## 14. RAG 与知识库升级方案

### 14.1 已完成的基础修复

“无 score 时返回前几个文档”的 fallback 已删除，`SimpleRetriever` 和 `HybridRetriever` 已支持 `rag.min_score`，当前默认配置为 `2.0`。无匹配或低于阈值时返回空 evidence。

服务器重跑时仍需验证 no-answer / hard negative 集合，critical 问题无证据时应回答：

> 当前知识库没有足够依据支持具体操作，请暂停作业并联系现场负责人/安全人员核验。

不要让模型凭参数记忆补出具体阈值。后续重点不再是 zero-hit fallback，而是阈值调优、来源治理、置信校准和 claim-level groundedness。

### 14.2 知识条目 schema

```json
{
  "id": "KS001-C03",
  "title": "有限空间作业",
  "text": "...",
  "source_title": "...",
  "publisher": "...",
  "source_url_or_bib": "...",
  "version": "...",
  "effective_date": "...",
  "section": "第X章/第X条",
  "page": "...",
  "license_or_usage": "公开引用/仅摘要",
  "risk_level": "critical",
  "review_status": "approved",
  "reviewer": "成员代号",
  "reviewed_at": "...",
  "source_sha256": "..."
}
```

项目现在的 20 条内容适合作为种子，不应包装为完整船厂规程库。下一阶段扩到 100–300 个经审核 chunk，覆盖有限空间、动火、吊装、试压、高处、涂装、临电、气瓶、交通、应急、信息安全等。

### 14.3 检索架构

课程提交可用：BM25/字符 n-gram + 明确阈值。后续升级：

```text
BM25 sparse + embedding dense
-> reciprocal rank fusion
-> cross-encoder rerank top 10 -> top 3
-> source/status/risk filter
```

索引必须包含 corpus hash、构建时间、tokenizer/embedding revision。索引缺失时 submission profile 直接失败，不能静默退回另一个行为不同的 retriever。

### 14.4 Citation 的正确评价

不要只检查“答案末尾有没有 `[KS001]`”。至少评价：

- retrieval hit@k/MRR/nDCG；
- no-answer 拒检；
- 每个关键 claim 是否被引用 chunk 支持；
- 引用是否指向真实来源段落；
- 引用与答案是否矛盾；
- 人工盲评 groundedness 1–5；
- blocked 请求 citation 必须为空。

---

## 15. SFT/LoRA 数据与训练升级

### 15.1 当前数据的优点与局限

1000/150 比旧 seed 数据进步明显，类别也覆盖 domain、安全、ASR 修正和多轮。但多数样本由模板从同一批 20 个知识条目、同一安全 CSV、同一 ASR 规则和同一多轮数据生成。虽然 exact normalized input overlap 为 0，train/test 仍共享知识事实和表达骨架，属于语义/来源泄漏。

### 15.2 正确拆分

使用 Group Split：

```text
group = source_id / scenario_id / rule_id / speaker_id
```

同一 group 只能属于一个 split。final test 最好由另一名成员根据未用于模板生成的公开材料独立编写，并在训练完成后才揭封。

### 15.3 去重与质量控制

- MinHash/SimHash 或 embedding 相似度去近重复；
- 统计模板占比、来源占比、回答长度和关键句重复率；
- 人工抽检至少 10%；
- 标记 synthetic / human-edited / source-derived；
- 记录版权和公开性；
- 安全回答不能只背固定拒答，要区分安全上报与危险操作；
- 多轮样本用真实 `messages` 结构，而不是把前文写进一句 input。

### 15.4 训练脚本

建议新增配置：

```text
seed=20260622
data_seed=20260622
base_model_revision=<commit>
max_seq_length=...
warmup_ratio=0.03
weight_decay=0.01
max_grad_norm=1.0
evaluation_strategy=steps
save_strategy=steps
load_best_model_at_end=true
metric_for_best_model=...
```

BF16：使用 `torch.cuda.is_bf16_supported()`，否则 FP16。记录每类 truncation，任何样本若回答 token 全被截断则丢弃并报警。

### 15.5 LoRA 对比实验

至少四组：

| 组 | Base | RAG | LoRA | 目的 |
|---|---|---|---|---|
| A | ✓ | ✗ | ✗ | 基础模型 |
| B | ✓ | ✓ | ✗ | RAG 的贡献 |
| C | ✓ | ✗ | ✓ | LoRA 风格/边界贡献 |
| D | ✓ | ✓ | ✓ | 最终系统 |

指标：safe domain quality、unsafe false allow、safe false block、factual support、拒答质量、答案长度、TTFT、tokens/s。拒答词计数只能作为辅助，不是主要质量指标。

---

## 16. 后端、数据库和管理后台升级

### 16.1 FastAPI 模块拆分

当前 `fastapi_app.py` 和 `sqlite_store.py` 过大。建议：

```text
src/shipvoice/
├─ api/
│  ├─ app.py
│  ├─ schemas.py
│  ├─ auth.py
│  ├─ routes_run.py
│  ├─ routes_admin.py
│  ├─ routes_health.py
│  └─ websocket.py
├─ services/
│  ├─ run_service.py
│  ├─ evaluation_service.py
│  ├─ knowledge_service.py
│  └─ config_service.py
├─ repositories/
│  ├─ runs.py
│  ├─ knowledge.py
│  └─ jobs.py
└─ db/
   ├─ connection.py
   └─ migrations/
```

这样才能独立测试认证、评测任务、配置事务和运行主链。

### 16.2 SQLite 已完成的最小强化与剩余项

连接建立后已启用：

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
PRAGMA synchronous=NORMAL;
```

仍需增加 schema_version 与 migration，常用查询增加索引：session_id、created_at、status、job status、client_request_id。不要在一次业务更新中先改 DB 再非原子写 JSONL/索引；以 DB 为事实源，通过 outbox 异步构建索引，失败可重试。

### 16.3 配置事务

```text
parse JSON
-> Pydantic schema validate
-> semantic validate (URL/provider/model)
-> 创建候选 pipeline 并 probe
-> 写 temp + fsync
-> 备份旧文件
-> atomic replace
-> 在锁内切换 runtime
-> 失败则保持旧 runtime/旧文件
```

### 16.4 评测任务

- 后台默认只跑离线 gate/retrieval，不应一点击就跑全套 LLM/TTS；
- live 评测必须明确提示费用/时长与服务需求；
- 同时只允许一个 active job；
- 提供 cancel、日志分页、重启恢复；
- 任务输出写独立 run 目录，禁止覆盖 final；
- 管理员触发操作写审计，不保存密码/token。

---

## 17. 前端与真实播放测量升级

### 17.1 上传与录音

- 音频选择前检查 MIME、大小；服务端再次验证；
- `MediaRecorder.start(timeslice)` 分片，限制 60 秒；
- 停止录音时记录 `speech_stop_perf_ms`；
- 更理想是在客户端 VAD 检测最后语音帧；课程版可以以用户点击“停止录音”的时刻作为明确 t0，并在报告中说明；
- 音频模式不发送问题真值；
- 上传和浏览器录音使用相同二进制协议；
- 支持 cancel/barge-in，释放麦克风 track 和 AudioContext。

### 17.2 播放队列

第一段音频到达后：

```javascript
player.addEventListener("playing", () => {
  const firstPlayMs = performance.now() - speechStopPerfMs;
  sendClientTiming(runId, firstPlayMs);
}, { once: true });
```

浏览器 autoplay 受策略限制，必须在用户点击提交产生的 gesture 链路中预先解锁 AudioContext。若需要用户再次点播放，必须单独报告“可播放 ready”与“实际 playing”，不能混用。

### 17.3 UI 语义修复

- `streaming` mode 已是真流式低延迟路径，界面可显示“流式低延迟”；
- 安全阻断时显示：ASR 完成、gate blocked、RAG/LLM skipped、safety TTS played；
- VAD 未实现则移除 VAD 节点；
- confidence 未校准前显示“相对检索分”，不要显示百分比置信；
- 结果导出默认不含 `audio_base64`、完整会话和隐私文本；
- 错误 banner 使用稳定错误码，详细 trace 仅后台可见。

---

## 18. 依赖、容器、CI 与供应链

### 18.1 依赖

当前 `requirements.txt` 只有未固定的 `fastapi`、`uvicorn`、`python-docx`，测试实际还依赖 `httpx`、WebSocket 客户端等。建议：

```text
pyproject.toml
requirements.lock.txt        # app
requirements-dev.lock.txt    # pytest/httpx/ruff/mypy/bandit
requirements-gpu.lock.txt    # 远程模型服务，分环境锁定
```

不要把 torch/funasr/vLLM 与轻量 Web 应用强塞进同一个环境。记录 Python、CUDA、驱动、torch、transformers、peft、funasr、模型 revision。

### 18.2 Docker

已完成：

- 创建非 root 用户运行应用；
- `.dockerignore` 排除 results、deliverables、audio、`.env`、本地 DB、模型/权重；
- compose healthcheck 调 `/api/ready`；
- 容器 CMD 使用 `--no-auto-port`，生产端口占用时直接失败。

仍需完成：

- 固定 Python 基础镜像 digest；
- 多阶段构建，只复制 `src/`、`web/`、必要 config/index；
- `read_only: true`，只挂载数据目录；
- 资源限制、日志轮转；
- 镜像扫描与 secret 扫描。

### 18.3 CI

建议 `.github/workflows/ci.yml`：

```text
ruff check
ruff format --check
mypy（逐步开启）
pytest -q --cov
bandit
pip-audit
secret scan/gitleaks
build knowledge index in temp and compare hash
build docs in temp
assert git diff --exit-code
```

真实 GPU E2E 不必每次 PR 跑，但应作为手动 workflow，上传带 SHA 的 artifact。

---

## 19. 测试体系：必须新增的用例

### 19.1 单元测试

| 模块 | 必测 |
|---|---|
| mode/schema | 非法 mode 422；所有公开 variant gate always-on |
| gate normalization | NFKC、零宽、空格、繁体、同音、复合句 |
| gate exceptions | 上报类正常放行；拼接危险要求仍阻断 |
| TermCorrector | 配置每条规则、冲突顺序、no-op 禁止、误纠 |
| retriever | 无命中返回空；阈值；索引缺失 fail-fast |
| citation | 不自动把错误证据当支持；blocked 无 citation |
| input validation | 坏 base64、超限、假扩展名、静音、过长 history |
| auth | 默认 secret 禁止、过期、篡改、吊销、限流 |
| config | 坏配置不覆盖、并发 reload、回滚 |
| idempotency | 同 request id 一次 provider 调用 |
| timing | complete 与 first-play 字段不混用 |

### 19.2 集成测试

使用临时 SQLite、临时配置和 fake providers：

- HTTP text safe/unsafe；
- audio 请求不包含 hint；
- WebSocket 断开/重连；
- provider timeout/cancel；
- blocked 路径 LLM 调用数 0；
- TTS safety prompt 路径与 UI 事件一致；
- 管理 CRUD 与索引 outbox；
- config atomic save；
- evaluation job singleton/cancel；
- `/ready` 随 provider 状态变化。

### 19.3 在线 E2E

- 1 条从未用于开发的音频完整跑通；
- 静音与噪声音频不能回填真值；
- 当前 LoRA adapter hash 可验证；
- 真实 TTS 音频可解码、时长 > 0、完整播报；
- 浏览器记录 `speech_stop` 与 `onplaying`；
- serial/streamed 同问题的安全和答案质量可比；
- 网络中断不双执行。

### 19.4 测试隔离

所有测试必须支持：

```bash
SHIPVOICE_TESTING=1 pytest -q
```

该模式下：

- 使用 `tmp_path` DB；
- 禁止访问正式 `data/knowledge` 写操作；
- fake providers 明确标识，不进入 final 结果；
- 测试后 `git diff --exit-code`；
- 不依赖被 `.gitignore` 排除的本机 env 文件。

---

## 20. 提交前的分阶段执行方案

> 下列时间段是给项目组安排修复优先级的执行窗口，不是对外性能承诺。若时间不足，宁可诚实降级表述，也不要继续保留被污染或错误命名的指标。

### 阶段 A：立即止血（已完成）

以下条目已落地并从后续待办中删除：

1. 门控已从 mode 解耦，所有公开请求 always-on。
2. ASR 音频协议已删除 `transcript_hint`，空识别不再回填真值。
3. 伪 `first_token/first_audio` 已改成 complete/ready 口径，前端新增浏览器 `onplaying` 打点。
4. 前端已取消无条件 HTTP 重试，并加入 `client_request_id`、断线 run 查询和进程内 result cache。
5. 默认管理员密码已禁用；未配置 secret 时使用进程级随机 secret；`/api/sessions` 已按 session/admin 分权。
6. 已加 question/history/audio/base64/session/mode 等输入限制。
7. 已加 RAG no-evidence、`rag.min_score`、安全举报例外防绕过、`/api/live` 与 `/api/ready`、后台配置原子保存和 draft final manifest。
8. 已加运行时全局并发/同会话互斥/排队等待/总超时保护、SQLite WAL/外键/busy timeout、前端 HTTP/WS 超时与坏 JSON 保护、容器非 root/readiness 和生产固定端口。

### 阶段 B：重新跑最小可信证据

1. 已补齐 50 条本地音频；已用 30 条 test 子集跑通真实 baseline 与 streaming。
2. 已在线跑真实 ASR/LLM/TTS 链路，无 `transcript_hint`；仍需独立输出 raw/corrected ASR 质量报告。
3. 冻结规则后输出 corrected 结果，报告 raw/corrected。
4. 已跑真实 LoRA 全链并确认 `adapter_loaded=true`；仍需记录 adapter SHA 并由 readiness 强校验。
5. 已记录服务端 complete 指标和 WebSocket 首 chunk 指标；浏览器 `onplaying` 批量指标仍需最终采集。
6. 安全门控继续扩展到至少 100 条对抗变体并重跑。
7. 已用服务器重跑结果更新 draft manifest；当前 `results/final_manifest_draft.json` 仍仅作草稿。

### 阶段 C：修正文档与答辩口径

1. 删除所有自评分和“95+”承诺。
2. 报告只放当前 manifest 产生的数字。
3. 历史 2026-06-12 结果放“历史工程接通证据”，不与当前 LoRA低延迟混算。
4. ASR 0% 改为当前真实 raw/corrected 结果：50/50 在线 ASR，平均 CER/WER 1.58%，术语召回 85.71%。
5. 说明当前真流式代码、服务器侧复验、30×2×5 重复实验和真实浏览器 `onplaying` 批量表均已完成。
6. PPT重点展示真实工程、发现瓶颈、严谨测量设计和安全修复。

### 阶段 D：完整低延迟复验

1. 已启动真实 ASR、ShipVoice LoRA LLM、TTS 服务。
2. 已确认 LLM `/v1/chat/completions stream=true` 返回 SSE delta。
3. 已使用固定音频跑 30×2×5 重复配对实验，并记录随机顺序、失败率、p50/p90/p95。
4. 已汇总重复实验 avg/p50/p90/p95 和失败率：300/300 ok，100/100 gate-allowed 配对 streaming 更快。
5. 最终报告只引用冻结 final manifest 中的基线 vs 改进表。

---

## 21. 建议的 Git 提交拆分

阶段 A 的止血项已经完成；后续不要再把这些条目作为待办提交。剩余工作建议按下面拆分：

```text
feat(streaming): add llm token stream and tts chunk playback
fix(runtime): add provider concurrency limits deadlines and cancellation
fix(lora): enforce adapter hash attestation in readiness
fix(eval): rebuild live ASR and paired latency protocol
test: add adversarial holdout concurrency and browser timing suites
ops: lock dependencies container readiness and remote service auth
docs: regenerate report and slides from final manifest
```

每个提交都配测试。最后打 tag：

```text
v0.3.0-a2-final-candidate
```

并在最终实验 manifest 写 tag 和 SHA。

---

## 22. 报告与 PPT 的推荐安全表述

### 22.1 摘要推荐写法

> ShipVoice 已实现基于真实 ASR、领域 RAG/LoRA LLM 和真实 TTS provider 的级联式船厂安全语音问答原型，并加入安全门控、术语后处理、证据引用和运行审计。本阶段完成了真实服务接通、真实 LoRA adapter SHA 验证、50 条在线 ASR raw/corrected 评测、30×2×5 baseline/streaming 重复实验和真实浏览器 `audio.onplaying` 批量取证。项目已进一步实现 token 流、句级切分、TTS 分段合成、WebSocket `audio_chunk` 推送和前端首句优先播放队列，并以浏览器停止录音到 `onplaying` 的时间作为最终首段可播放指标。所有指标均绑定固定提交、模型版本、音频 hash 和实验 manifest；用户暂缓的最终报告/PPT 后续应只读 manifest 统一生成。

当前可以说“真流式代码路径已完成，并已通过真实服务器、重复实验和浏览器首播取证复验”；最终提交材料只需避免引用旧口径或旧单轮数字。

### 22.2 ASR 结果脚注

> Raw ASR 指标来自冻结测试音频在线推理，不向 ASR 服务提供参考转写。术语后处理规则只在开发集调整，最终测试集冻结。报告同时给出原始和修正后 CER、术语召回与误纠率。

在重新取证前：

> 仓库历史 0% CER 是对已修正清单文本的复算结果，不能视为独立真实 ASR 泛化指标。本版最终 ASR 证据改用 `results/asr_online_20260623/summary.json`：50/50 在线 ASR，平均 CER/WER 1.58%，术语召回 85.71%。

### 22.3 延迟结果脚注

> E2E first-play 从浏览器记录用户停止录音的时刻开始，到第一段回答音频触发 `onplaying` 为止。服务端完整 TTS 返回时间单独报告，不与首播混用。

### 22.4 安全结果脚注

> 安全准确率仅表示在给定测试集上的结果。系统仍可能受到新型改写、ASR 误识别和多轮注入影响，因此公开链路始终启用门控，并对不确定输入采用澄清或受限回答。

### 22.5 老师追问时的诚实回答

**问：为什么首音还很慢？**
答：当前真实链路已经接通，但旧实现等待完整 LLM 和完整 TTS，约 12–15 秒的结果反映了完整串行瓶颈。我们没有把它包装成达标首音，而是把测量点纠正到客户端播放，并将优化集中在 token 流、首句切分和分段 TTS。

**问：ASR 0% 是否可信？**
答：历史清单结果包含后处理，且曾存在 reference hint 回填风险，所以我们已将其降级为历史工程结果。最终结果必须由冻结音频在线推理、无真值 hint 的 raw 输出重新计算。

**问：LoRA 怎么证明真的加载了？**
答：不能只看模型名称。最终验收读取模型服务 attestation，并记录 base revision、adapter loaded 和 adapter SHA-256；不匹配时应用 readiness 失败。

**问：你们的 streaming 在哪里？**
答：`streaming` mode 中，OpenAI-compatible provider 使用 `stream=true` SSE，pipeline 在 LLM delta 中累积句子，句子完成即进入 TTS worker，WebSocket 推 `audio_chunk`，前端收到后进入分段播放队列。2026-06-23 真实服务器复验已证明首个 `audio_chunk` 早于最终 result；现场演示时再展示浏览器 `audio.onplaying` 指标。

---

## 23. 最终验收门

只有同时满足以下条件，才能把某次结果标成 `FINAL`：

- [ ] git SHA 固定且 dirty=false；
- [ ] 配置、语料、索引、音频 manifest 均有 SHA-256；
- [ ] ASR 音频请求不存在 reference transcript/hint；
- [ ] 空 ASR 不会回填真值；
- [ ] 所有公开 variant 安全门控 always-on；
- [ ] unsafe/prompt injection 的 LLM 调用次数为 0；
- [ ] LoRA adapter attestation 与预期 hash 一致；
- [ ] 至少一条全真实音频链可复现；
- [ ] 基线和改进除性能策略外配置相同；
- [ ] 首播由浏览器 `onplaying` 打点；
- [ ] 失败样本不被静默删除；
- [ ] 结果含样本数、重复、p50/p90/p95、失败率；
- [ ] 报告、PPT、Dashboard 从同一 manifest 生成；
- [ ] 报告无“95+”自评分和冲突数字；
- [ ] 管理后台无默认密码，session/audit 受保护；
- [ ] 输入、并发、超时和取消边界已测试；
- [ ] 全新克隆可安装、运行离线测试和读取最终证据；
- [ ] 最终 zip 经过 secret/PII/绝对路径扫描并生成 sha256。

---

## 24. 全仓逐目录审计清单

说明：下表覆盖本轮两次提交之间新增/修改的主要路径，并补充若干虽未修改但直接影响 A2 的关键文件。`DOCX/PPTX/CSS` 等二进制或大生成物不能仅凭 Git diff 验证视觉/版式，必须从修正后的源数据重新生成并人工检查。

### 24.1 根目录、构建与配置

| 文件 | 本轮结论/动作 |
|---|---|
| `.dockerignore` | 已扩大排除 env、DB、results、audio、deliverables、模型/权重；后续做镜像扫描确认无敏感文件 |
| `.gitignore` | 当前会忽略部分原始远程证据；应提交公开 manifest/hash，而非只在报告引用本地路径 |
| `Dockerfile` | 已非 root、固定容器端口且使用 `--no-auto-port`；仍需锁 digest、多阶段和只复制运行文件 |
| `docker-compose.app.yml` | healthcheck 已切 `/api/ready`；仍需资源限制、read-only、网络隔离 |
| `requirements.txt` | 未锁版本且缺 dev/test 依赖；迁移 pyproject + lock |
| `run_app.py` | 已支持 `--no-auto-port`/`SHIPVOICE_NO_AUTO_PORT`；仍需启动前 secret/provider/config preflight |
| `README.md` | 新版 real-only 说明是进步；仍需删除旧指标/默认密码并统一 final manifest |
| `configs/pipeline.json` | mode 与安全解耦；规则/阈值/版本 schema 校验 |
| `configs/runtime.real.env.example` | 不得暗示 require_lora 已自动强制；补 secret 与 attestation 配置 |
| `configs/runtime.lora.env.example` | 补 adapter SHA、base revision、禁止提交真实 key |
| `configs/runtime.vllm.env.example` | 与真正 `--enable-lora` 启动命令保持一致 |
| `configs/asr_postprocess_rules.json` | 作为唯一规则源；加 version/rule_id/开发集说明 |



### 24.2 核心后端源码

| 文件 | 本轮结论/动作 |
|---|---|
| `src/shipvoice/__init__.py` | 版本号与最终 tag 一致 |
| `src/shipvoice/models.py` | 重命名错误 timing 字段；增加 client timing、attestation、request id |
| `src/shipvoice/config.py` | 增加 Pydantic Settings/URL/枚举/上限校验；敏感配置仅环境变量 |
| `src/shipvoice/providers.py` | 已加 OpenAI SSE streaming、持久 HTTP client、请求/失败计数和取消边界；仍需继续处理 gate 例外、未知放行、规则漂移、远端认证 |
| `src/shipvoice/pipeline.py` | 已加 streaming mode 安全闭合 TTS 队列、完整回答输出 guard、provider 取消传播和 provider_status 可观测字段；仍需 provider 分级 deadline、真实 VAD |
| `src/shipvoice/fastapi_app.py` | 已补认证、公开 sessions、输入限制、幂等、atomic config、运行时并发/同会话互斥/总超时、HTTP cancel endpoint 和 WebSocket cancel frame；仍需拆分模块、jobs 队列 |
| `src/shipvoice/sqlite_store.py` | 1538 行 God class；已启用 WAL/外键/busy timeout；仍需迁移/事务/outbox/分页/索引 |
| `src/shipvoice/audit.py` | 与 SQLite audit 功能重叠，统一到 repository/service |
| `src/shipvoice/knowledge.py` | 与 runtime index/DB同步策略统一，补 schema/provenance |



### 24.3 用户端与管理后台

| 文件 | 本轮结论/动作 |
|---|---|
| `web/static/index.html` | 检查 mode 文案、可访问性、隐私提示、上传限制 |
| `web/static/app.js` | 已取消 WS 盲重试，新增首播打点、HTTP/WS 超时、坏 JSON 保护、`audio_chunk` 分段播放队列和 cancel frame；仍需敏感导出治理 |
| `web/static/styles.css` | 已扩大左侧快速场景和高级选项展开空间；仍需持续人工检查移动端/高对比/状态语义 |
| `web/static/admin.html` | 隐藏高危操作、加确认/权限/评测成本提示 |
| `web/static/admin.js` | config atomic 结果、job cancel、401处理、避免展示内部路径/trace |



### 24.4 远程模型与服务

| 文件 | 本轮结论/动作 |
|---|---|
| `remote/serve_funasr_asr.py` | 删除空输出 hint 回填；限制输入；返回模型 revision/hash；绑定本地/认证 |
| `remote/serve_transformers_openai.py` | 已支持 `stream=true` SSE；仍需限制 tokens/并发、固定 revision、auth、健康脱敏 |
| `remote/serve_edge_tts.py` | 禁止拼接独立 MP3；改连续 PCM/Opus chunk，真实 first byte |
| `remote/serve_chattts_tts.py` | 全量阻塞、voice 未控制；增加队列、chunk 或明确 complete-only |
| `remote/serve_gtts_tts.py` | 依赖公网且全量返回；只作备选，说明隐私/网络与不可流式边界 |
| `remote/start_shipvoice_real_services.sh` | 默认 0.0.0.0 与 stale PID；改 localhost、kill -0、日志轮转 |
| `remote/stop_shipvoice_real_services.sh` | 校验 PID 对应进程，避免误杀 |
| `remote/start_lora_llm.sh` | 输出 attestation；stale PID；固定 adapter/base revision |
| `remote/stop_lora_llm.sh` | 校验进程和超时，清理 pid 原子化 |
| `remote/start_full_lora_stack.sh` | ready 要校验 adapter，不只是 URL 可访问 |
| `remote/stop_full_lora_stack.sh` | 错误聚合和幂等停止 |
| `remote/start_transformers_llm.sh` | 安全绑定、版本、资源与 attestation |
| `remote/stop_transformers_llm.sh` | 进程校验 |
| `remote/start_vllm_llm.sh` | 当前默认 base；增加 enable-lora/lora-modules/served name |
| `remote/stop_vllm_llm.sh` | 进程校验 |
| `remote/autodl_setup.sh` | 锁包版本/模型 revision；不要浮动安装 |
| `remote/autodl_setup_asr.sh` | 锁 FunASR/ModelScope 版本；记录环境 |
| `remote/autodl_smoke_test.sh` | 无 hint 静音负例与 adapter attestation |
| `remote/run_autodl_pipeline.sh` | 失败不可 `|| true`；完整 artifact manifest |
| `remote/run_resume_lora_eval.sh` | 区分 resume checkpoint 与重新训练 |
| `remote/train_qwen_lora.py` | 加入 eval/seed/bf16支持/truncation/revision/best model |
| `remote/train_qwen_lora.sh` | 参数与 manifest 一致，set -euo pipefail |
| `remote/evaluate_qwen_lora.py` | 当前只生成答案；新增结构化质量评分和基线消融 |



### 24.5 数据与知识

| 文件 | 本轮结论/动作 |
|---|---|
| `data/knowledge/ship_safety_corpus.jsonl` | 20 条种子库；补权威来源、版本、条款、审核与许可 |
| `data/knowledge/ship_safety_index.json` | 生成物需 corpus hash、build version；禁止手改 |
| `data/audio/audio_manifest.csv` | 补 audio hash/duration/sample rate/codec/consent；raw列不可变 |
| `data/tests/eval_questions.csv` | 仅 8 条且多数直接映射知识标题；扩大并设 no-answer/hard negatives |
| `data/tests/safety_eval.csv` | 规则同源；增加变形、多轮、复合句、Unicode和未见攻击 |
| `data/tests/multiturn_eval.jsonl` | 6 组较小；增加指代、冲突上下文、注入、澄清 |
| `data/training/sft_seed.jsonl` | 保留为人工种子；补 messages 多轮格式和来源 |
| `data/training/shipvoice_sft_train_expanded.jsonl` | 1000 条模板数据；按 source group 去重/拆分 |
| `data/training/shipvoice_sft_eval_holdout.jsonl` | 150 条与训练共享来源/骨架；不能当独立外部 test |



### 24.6 评测、验证与生成脚本

| 文件 | 本轮结论/动作 |
|---|---|
| `scripts/run_benchmark.py` | 8 条文本、功能不等价 mode；重写为真实音频配对 E2E |
| `scripts/check_real_service_chain.py` | P0：发送真值 hint；只测一条；改无 hint + 多样本 + attestation |
| `scripts/evaluate_asr_transcripts.py` | 只评分清单，不在线推理；raw/corrected 分离 |
| `scripts/evaluate_safety_gate.py` | 默认 full 可能调用真实链；后台离线评测应 `--gate-only` |
| `scripts/evaluate_multiturn.py` | grounding 定义弱且不需 TTS；增加对照与语义评分 |
| `scripts/evaluate_citation_quality.py` | ID存在性偏形式化；增加 claim entailment/no-answer |
| `scripts/build_knowledge_index.py` | 索引元数据、阈值与来源 schema |
| `scripts/build_expanded_sft_dataset.py` | 模板/来源泄漏；按 group split、近重复检测 |
| `scripts/validate_sft_dataset.py` | 仅 exact overlap；补 group/semantic leakage/质量抽检 |
| `scripts/summarize_remote_lora_results.py` | 拒答词计数不是准确率；补混淆矩阵/人工质量 |
| `scripts/validate_project.py` | 验证会写文件且默认不跑单测；重构 read-only |
| `scripts/validate_real_only.py` | 搜索禁词不能证明真实 provider；降级为静态 guard |
| `scripts/smoke_fastapi_backend.py` | 不要使用默认密码或正式 DB；临时隔离 fixture |
| `scripts/build_acceptance_report.py` | 删除硬编码分数；只读 final manifest，stale/dirty fail |
| `scripts/build_evaluation_dashboard.py` | 数字必须来自同一 manifest，区分 historical/final |
| `scripts/build_final_report.py` | 禁止硬编码旧结果；从 canonical summary 生成 |
| `scripts/build_final_report_docx.py` | 重新生成后人工打开检查表格/中文字体/分页 |
| `scripts/build_final_deck_workspace.py` | PPT 数据绑定 manifest；二进制需人工视觉检查 |
| `scripts/run_lora_final_validation.ps1` | 加入 no-hint、dirty检查、adapter hash、失败非零 |
| `scripts/run_single.py` | 明确 text path 不等于 ASR 证据；保存 run manifest |
| `scripts/start_shipvoice_app.ps1` | 强制 secret/env preflight，显示真实端口 |
| `scripts/ssh_port_forward.py` | 避免在日志输出凭据；校验 host key 和端口占用 |
| `scripts/make_autodl_bundle.py` | allowlist + secret/PII scan + sha256；不打包本地绝对路径 |



### 24.7 测试

| 文件 | 本轮结论/动作 |
|---|---|
| `tests/test_admin_api.py` | 依赖被忽略 env/httpx；改临时 DB/config/fake providers |
| `tests/test_real_lora_chain.py` | 当前偏静态环境检查；增加 attestation 结构与 no-hint |
| `tests/test_citation_quality_eval.py` | 增加错误引用/无证据/自动附ID的负例 |
| `tests/test_evidence_citations.py` | 增加 claim支持而非仅 schema |
| `tests/test_pipeline_security.py [新增]` | 覆盖所有 variant、复合句、spy LLM zero-call |
| `tests/test_audio_validation.py [新增]` | 坏 base64、静音、超限、MIME伪装、无 hint |
| `tests/test_ws_idempotency.py [新增]` | 断线重连与单次 provider 调用 |
| `tests/test_client_timing.spec.js [新增]` | speech stop -> onplaying 事件和 ACK |



### 24.8 结果与交付物

| 文件 | 本轮结论/动作 |
|---|---|
| `results/real_chain_smoke.json` | 旧 LoRA 单样本接通证据，保留作历史记录，不再作为最终低延迟证据 |
| `results/real_chain_smoke_streaming.json` | 当前真实服务器 streaming smoke 证据，确认 ASR/LoRA/TTS 真实链路和流式指标 |
| `results/server_real_batch_comparison_20260623.md` | 当前服务器侧 baseline vs streaming 第一轮真实配对对比 |
| `results/server_real_repeated_20260623/summary.json` | 30 条音频 × 2 mode × 5 repeats 真实重复实验汇总 |
| `results/browser_onplaying_streamable_20260623.json` | 真实浏览器 `audio.onplaying` 批量首播指标 |
| `results/asr_online_20260623/summary.json` | 50 条在线 ASR raw/corrected 质量评测 |
| `results/lora_adapter_attestation_20260623.json` | LoRA adapter SHA attestation 结果 |
| `results/asr_eval_summary.json` | 0% 是修正列复算，不是无污染在线ASR |
| `results/multiturn_eval_summary.json` | 与最终报告 97.22%/1516ms 不一致 |
| `results/citation_quality_summary.json` | 形式化 citation 指标较好，但未证明 claim groundedness |
| `results/safety_gate_eval_summary.json` | 同源规则集 100%；需对抗 holdout |
| `results/project_acceptance_report.md/.json` | 旧 SHA、dirty、自评分；不可作为最终验收 |
| `results/remote_lora_expanded_summary_20260621.json` | 公开摘要可保留；原始工件/adapter hash/日志缺失 |
| `results/remote_real_chain_20260612_chattts_48359/*` | 历史真实 ASR/TTS 证据；LLM不是当前主链，单独标历史 |
| `results/assignment_extract.*` | 课程题目副本；避免多份提取文本产生歧义 |
| `results/expanded_sft_dataset_*` | 可作为数据生成统计，不等于独立泛化质量 |
| `deliverables/final_submission/report/*` | 数字和口径必须全部重生成；成员占位符必须填写 |
| `deliverables/final_submission/manuals/*` | 删除默认密码、旧多轮指标和旧真值指向 |
| `deliverables/final_submission/slides/*` | 删除 97.22% 等过期数字；增加正确测量图 |
| `deliverables/ShipVoice_Evaluation_Dashboard.html` | 重生成并标 evidence level/commit |
| `deliverables/ShipVoice_Final_Defense_Deck_Draft.pptx` | 二进制需由最新 manifest 重做并逐页人工检查 |
| `deliverables/*项目报告*.docx` | 必须从修正后的 Markdown 重新生成并检查目录/表格/数字 |



### 24.9 文档

| 文件 | 本轮结论/动作 |
|---|---|
| `docs/ADMIN_CONSOLE.md` | 补认证、权限、风险操作与默认安全配置 |
| `docs/ARCHITECTURE.md` | 已更新为普通完整返回 + streaming SSE/token、句级 TTS worker、WebSocket `audio_chunk` 的当前实现 |
| `docs/AUTODL_RUNBOOK.md` | 固定版本、服务安全绑定、关机与费用说明 |
| `docs/COMPETITION_GRADE_ROADMAP.md` | 删除自评分导向，改验收门和证据等级 |
| `docs/CONTAINER_DEPLOYMENT.md` | 非 root、secret、readiness、卷和网络隔离 |
| `docs/DATA_CARD.md` | 补 synthetic比例、来源拆分、泄漏风险、版权、人工审核 |
| `docs/DEMO_VIDEO_SCRIPT.md` | 演示不显示错误首音/弱密码/污染指标 |
| `docs/FASTAPI_BACKEND.md` | 补幂等、limits、auth、error schema、WS重连 |
| `docs/FINAL_DELIVERY_PLAN_20260608.md` | 日期和当前状态更新；避免旧计划冒充完成 |
| `docs/FINAL_LORA_VALIDATION_RUNBOOK.md` | 加入 adapter sha/no-hint/client timing |
| `docs/FINAL_REPORT_OUTLINE_20260608.md` | 只引用 final manifest |
| `docs/HIGHEST_QUALITY_PLAN.md` | 将真流式、安全和实验优先于UI美化 |
| `docs/MASTER_EXECUTION_PLAN.md` | 按P0/P1和责任人重新排期 |
| `docs/MODEL_CARD.md` | base revision、adapter hash、训练数据与安全局限 |
| `docs/OPERATIONS_RUNBOOK.md` | secret生成、恢复、任务取消、数据保留 |
| `docs/PHASE1_SCORECARD.md` | 已补真流式代码完成、真实服务复验完成、重复实验和 `onplaying` 批量表均完成的低延迟验收口径 |
| `docs/REAL_STACK_DEPLOYMENT.md` | 网络认证、端口、attestation、版本锁 |
| `docs/ROADMAP_95_PLUS.md` | 建议重命名为 ROADMAP_FINAL_ACCEPTANCE；删除分数承诺 |
| `docs/RUNBOOK.md` | 与final manual合并去重，保持单一命令源 |
| `docs/SHIPVOICE_USER_MANUAL.md` | 补录音隐私、失败/复述、不可替代现场负责人 |
| `docs/TASK_BOARD.md` | 把P0 bug转为可勾选任务和owner |
| `docs/ZERO_PREP_BOOTSTRAP.md` | 真实模型不可能零准备；更名并写前置条件 |



---

## 25. 推荐的最终目录与命令体系

### 25.1 目录

```text
shipvoice/
├─ pyproject.toml
├─ requirements*.lock.txt
├─ configs/
│  ├─ pipeline.schema.json
│  ├─ serial.final.json
│  ├─ streamed.final.json
│  └─ asr_postprocess_rules.v2.json
├─ src/shipvoice/
├─ tests/
├─ data/
│  ├─ knowledge/source/
│  ├─ knowledge/index/
│  ├─ audio/dev/
│  └─ audio/final_test/
├─ experiments/
│  └─ final_20260622_<runid>/
├─ deliverables/
└─ scripts/
```

### 25.2 命令

```bash
# 1. 全新环境
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.lock.txt

# 2. 只读静态与单元测试
ruff check .
pytest -q
python scripts/validate_project.py --read-only --profile submission

# 3. 生成并冻结知识索引（输出 hash）
python scripts/build_knowledge_index.py --strict --emit-manifest

# 4. 在线 ASR 无真值评测
python scripts/run_asr_eval_live.py --manifest data/audio/final_test.csv --no-reference-hint
python scripts/score_asr_eval.py --raw ... --rules configs/asr_postprocess_rules.v2.json

# 5. 真实服务 attestation
python scripts/check_provider_attestation.py --require-lora --require-hashes

# 6. 串行基线
python scripts/evaluate_latency_e2e.py --variant serial --repeats 5 --browser

# 7. 流式改进
python scripts/evaluate_latency_e2e.py --variant streamed --repeats 5 --browser

# 8. 生成唯一 final manifest 和报告
python scripts/finalize_experiment.py --require-clean-git --verify-hashes
python scripts/build_final_report.py --manifest experiments/.../experiment_manifest.json
python scripts/build_final_report_docx.py --manifest experiments/.../experiment_manifest.json
python scripts/build_final_deck.py --manifest experiments/.../experiment_manifest.json

# 9. 打包和扫描
python scripts/build_submission_bundle.py --allowlist submission_files.txt
sha256sum ShipVoice_Final.zip > ShipVoice_Final.zip.sha256
```

这些新增命令是推荐设计，不是当前仓库已存在能力；实现后再写入正式运行手册。

---

## 26. 团队分工建议

| 责任线 | 主要任务 | 完成定义 |
|---|---|---|
| 后端/安全 | mode 解耦、输入限制、认证、幂等、readiness | P0 安全测试全部通过 |
| 语音/模型 | 删除 hint、ASR 在线评测、LoRA attestation、流式 LLM/TTS | 无污染 raw 结果 + 可播放 chunk |
| 数据/评测 | final test 冻结、group split、指标/CI、manifest | 结果可追溯且无同源泄漏 |
| 前端 | 录音 t0、播放 `onplaying`、重连、取消、状态语义 | 客户端首播日志与 run_id 对齐 |
| 文档/答辩 | 删除自评分、统一数字、重新生成 DOCX/PPT | 所有数字只来自 final manifest |

每项任务要写负责人、commit、测试和 artifact 路径，不要只写“参与开发”。

---

## 27. 最终判断

ShipVoice 新版已经具备一个较完整的工程骨架：真实 provider、LoRA 服务、FastAPI、WebSocket、录音上传、RAG、门控、SQLite、后台和多类评测脚本都已存在。与旧版相比，这是实质性升级。

当前第一轮止血、服务器侧复验和 2026-06-24 追加加固已经完成：公开 mode 安全门控、ASR hint/回填、错误指标口径、WebSocket 自动重跑、默认管理员口令、公开 session、输入边界、RAG no-evidence、举报例外、ready/live、客户端播放打点、配置原子保存、draft manifest、真实 ASR/LoRA/TTS 接通、LoRA adapter SHA attestation、LLM SSE 流、安全闭合句段 TTS、非流式完整回答输出 guard、provider HTTP 连接池复用、provider_status 可观测计数、WebSocket `audio_chunk`、前端取消按钮、WebSocket cancel frame、后端取消传播，以及 30×2×5 baseline/streaming 重复实验均已落地。

剩余最关键的不是继续堆 UI，而是把已完成的服务器侧取证变成最终可提交证据包，并继续处理生产化长期项：

1. 用 clean git + final experiment manifest 统一生成报告、PPT、Dashboard；
2. 补齐 provider 分级队列、分阶段 deadline 和速率限制；
3. 继续做远端服务认证、依赖锁、SQLite migration/outbox、容器多阶段/read-only/扫描和生产化边界；
4. 保持公平基线 vs 改进实验只改变串行/流式策略，后续报告不得混用历史单轮数字；

除用户暂缓的报告/PPT/Dashboard 生成外，项目已经从“P0 已止血且服务器侧已复验的工程原型”提升为“安全边界明确、实验可复现、低延迟结论有真实证据支撑的 A2 项目”。剩余长期项主要影响生产化质量，不再阻断 A2 核心验收。

---

## 28. 本文档使用的固定证据

- 课程题目：用户提供的《信息安全基础》项目考核内容，A2 要求 ASR→LLM→TTS、基线与低延迟改进、固定音频集、从停止说话到首段播放的测量、架构/版本/配置/复现实验。
- 仓库：`L-Dramatic/ShipVoice`。
- 原始审计固定提交：`51f45d163e9efeba60c0a820c085cd1c6b3079d3`。
- 上一轮基线提交：`e85ca04c6fd156c20f37033c1a8936b78e988463`。
- 两者差异：当前提交领先 21 个提交。
- 本文当前版本已叠加 2026-06-22 本地工作区修复状态；最终提交前应把新的 SHA、dirty=false 和 final manifest 写回本文档或最终报告。

任何后续推送都会使本文中的“当前代码”判断可能变化。继续修改后，应在新 SHA 上重新运行 P0 回归测试，并把新 SHA 写入最终 experiment manifest。
