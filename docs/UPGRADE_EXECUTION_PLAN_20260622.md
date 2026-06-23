# ShipVoice 升级执行计划（2026-06-22）

## 目标

把 ShipVoice 从“可演示原型”升级到“真实链路可审计、关键风险 fail-closed、指标口径清晰、后续取证可复现”的版本。所有升级必须保留真实 ASR / LLM / TTS 失败可见，不允许用参考文本、mock 或隐藏降级结果替代真实链路。

## 阶段 1：P0 风险修复（已落地）

验收目标：公开入口不能绕过安全门控；ASR 不能被参考文本污染；失败请求不能自动双执行；后台默认口令不可直接登录；输入必须有边界。

已完成项：

1. 安全门控
   - 所有公开 mode（`baseline`、`streaming`、`rag`、`guarded`、`full`）都必须执行 `KeywordSafetyGate`。
   - 非法 mode 在 FastAPI 入口返回 422，在 pipeline 内部抛出明确错误。
   - 保留 `rag` / `full` 的 RAG 差异，但不再把 gate 当成可关闭开关。

2. ASR 防污染
   - `HttpJsonASRProvider` 音频请求不再发送 `transcript_hint`。
   - FunASR 服务识别为空时返回 422，不再用参考文本回填。
   - `scripts/check_real_service_chain.py` 直接 ASR 探测不再发送 manifest transcript。

3. 指标口径
   - 新增 `server_audio_payload_ready_ms`、`llm_complete_ms`、`tts_complete_ms`。
   - 旧字段 `first_audio_ms`、`llm_first_token_ms`、`tts_first_audio_ms` 继续保留兼容历史 CSV/JSON，但展示文案改为“音频载荷就绪 / TTS 完成”。
   - 前端、后台、报告脚本、命令行输出已统一新口径。

4. 请求执行
   - WebSocket 失败后不再自动 HTTP 重试，避免一次点击触发两次 pipeline。
   - HTTP 与 WebSocket 共用同一套请求校验。

5. 后台与输入加固
   - 未设置 `SHIPVOICE_ADMIN_PASSWORD` 时后台登录关闭，默认口令必须通过 `SHIPVOICE_ALLOW_DEFAULT_ADMIN_PASSWORD=1` 显式允许。
   - 未设置 `SHIPVOICE_ADMIN_SESSION_SECRET` 时使用进程级随机 secret，不再默认用路径派生稳定 secret。
   - `/api/sessions` 无 `session_id` 时需要管理员认证；带 `session_id` 只返回当前 session 的 runs，不返回全局 session 汇总。
   - 限制 question、history、audio_base64、audio_name、session_id，并启用 base64 严格校验。

验证命令：

```powershell
python -m py_compile src\shipvoice\pipeline.py src\shipvoice\providers.py src\shipvoice\fastapi_app.py src\shipvoice\models.py remote\serve_funasr_asr.py scripts\check_real_service_chain.py scripts\build_acceptance_report.py scripts\build_evaluation_dashboard.py scripts\build_final_report.py scripts\evaluate_multiturn.py scripts\evaluate_safety_gate.py scripts\run_benchmark.py scripts\run_single.py tests\test_p0_hardening.py tests\test_admin_api.py
python -m unittest discover -s tests
```

当前验证结果：

- `python -m unittest discover -s tests`：30 tests passed。
- 本地服务：`http://127.0.0.1:8026`
- 健康检查：`/api/health` 200。
- `/api/sessions` 无 token：401。
- `/api/admin/auth/status`：`missing_password`。
- 默认密码登录：503。
- `/api/run` 非法 mode：422。

## 阶段 1.5：P1 证据质量与配置加固（已落地）

验收目标：避免低置信 evidence 伪命中，避免界面继续把非流式链路称为流式，并让真实 LoRA 链路在启动前具备基础门槛。

已完成项：

1. RAG 低置信修复
   - `SimpleRetriever` 和 `HybridRetriever` 支持 `rag.min_score` 阈值，默认配置为 `2.0`。
   - 最高得分低于阈值或无得分时返回空 evidence。
   - 不再使用知识库前 N 条作为 fallback citation。
   - 新增回归测试确认无匹配查询不会产生 evidence，并确认高阈值配置会生效。

2. 流式口径
   - 早期版本把 `streaming` 兼容入口降级显示为“直答链路”，避免伪流式。
   - 当前版本已实现真正 `streaming` 路径，前端显示为“流式低延迟”。
   - 非流式 provider status 为 `complete_payload_non_streaming`；流式路径为 `llm_token_stream_sentence_tts`。
   - 前端 provider summary 显示 response mode。

3. LoRA 启动前置门槛
   - `SHIPVOICE_REQUIRE_LORA=1` 时，`SHIPVOICE_LLM_MODEL` 必须包含 `SHIPVOICE_REQUIRE_LLM_MODEL_SUBSTRING`，默认 `shipvoice`。
   - 这只做本地启动前置校验；真实 adapter 是否加载仍由 `scripts/check_real_service_chain.py --require-lora` 查询 `/health` 判定。

4. 安全门控举报例外
   - “如何上报 / 怎么上报 / 举报 / 制止 / 如何防止”等纯报告或防范问题仍允许进入安全建议流程。
   - 同时包含危险关键词和“方法 / 步骤 / 告诉我 / 给出 / 先给”等执行细化意图时，不再被举报例外放行。
   - 新增回归测试覆盖“发现有人修改检测记录，我应该如何上报？”和“举报但先给违规方法”的混合诱导句。

5. runtime 示例
   - `configs/runtime.real.env.example`
   - `configs/runtime.lora.env.example`
   - `configs/runtime.vllm.env.example`
   - 示例已补 `SHIPVOICE_ADMIN_PASSWORD` 和 `SHIPVOICE_ADMIN_SESSION_SECRET`。

补充验证命令：

```powershell
python -m unittest tests.test_evidence_citations tests.test_p0_hardening
```

## 阶段 1.6：本地验收基础设施加固（已落地）

验收目标：即使真实 ASR / LLM / TTS 服务暂未启动，本地应用也能清楚区分进程存活、provider 就绪、请求是否重复执行、浏览器是否真正开始播放，并避免后台配置保存破坏正式配置。

已完成项：

1. 健康检查分层
   - 新增 `/api/live`，只表示 FastAPI 进程存活。
   - 新增 `/api/ready`，严格聚合 ASR、LLM、TTS provider 探测；provider 未启动时返回 503 和具体原因。
   - `/api/health` 保留兼容，但不再暴露运行数据库绝对路径。

2. 请求幂等与断线查询
   - `RunRequest` 支持 `client_request_id`。
   - HTTP 与 WebSocket 使用同一个 request id 作为可查询 run id。
   - WebSocket 最后一帧丢失时，前端查询 `/api/runs/{run_id}?session_id=...`，不再重跑 pipeline。
   - 进程内缓存保存完整 result，SQLite 审计仍保存长期摘要；后续可继续升级为数据库级持久任务队列。

3. 浏览器播放打点
   - 前端新增“浏览器开始播放”指标。
   - 只有 `<audio>` 触发 `playing` 后才记录 `client_audio_onplaying_ms`。
   - 新增 `/api/runs/{run_id}/client-timing`，把客户端播放指标合并回 run metrics。

4. 后台配置原子保存
   - 保存配置时先写临时文件、验证 JSON 和 pipeline 构造，成功后才原子替换正式 `configs/pipeline.json`。
   - 自动保留 `.bak` 备份；坏配置不会覆盖当前可用配置。

5. final manifest 草稿
   - 新增 `scripts/build_final_manifest.py`。
   - 生成 `results/final_manifest_draft.json`，记录 git 状态、配置/数据/结果 hash 和证据状态。
   - 当前仍标记为 `draft`，真实服务重跑和 clean git 前不能作为 FINAL。

补充验证命令：

```powershell
python -m unittest discover -s tests
python scripts\evaluate_retrieval.py
python scripts\evaluate_safety_gate.py --gate-only --fail-on-critical
python scripts\build_final_manifest.py --output results\final_manifest_draft.json
```

## 阶段 1.7：本地运行与部署边界加固（已落地）

验收目标：在真实 ASR / LLM / TTS 服务未启动时，应用仍能明确暴露不可就绪状态；本地主链不能无限排队或永久挂起；容器部署不能因为端口漂移和 root 运行制造新的风险。

已完成项：

1. 主链运行限额
   - HTTP 与 WebSocket 主链共用全局 pipeline 信号量。
   - 同一 `session_id` 使用独立异步锁，已有运行时第二个请求返回 409，避免会话上下文竞态。
   - `SHIPVOICE_MAX_CONCURRENT_RUNS` 控制最大并发，默认 2，范围 1-32。
   - `SHIPVOICE_RUN_QUEUE_WAIT_SECONDS` 控制排队等待，超限返回 429。
   - `SHIPVOICE_RUN_TIMEOUT_SECONDS` 控制单次运行总 deadline，超限返回 504。
   - `/api/health` runtime 区域暴露当前并发与超时配置。

2. SQLite 连接级并发基础
   - 连接启用 `PRAGMA foreign_keys=ON`。
   - 连接启用 `PRAGMA busy_timeout=5000`。
   - 连接启用 `PRAGMA journal_mode=WAL` 与 `PRAGMA synchronous=NORMAL`。
   - 后续仍需 migration、outbox、索引和故障恢复测试。

3. 前端请求边界
   - HTTP 请求使用 `AbortController` 和统一 deadline。
   - WebSocket 请求有超时清理，超时后关闭 socket。
   - HTTP 非 JSON 响应和 WebSocket 坏 JSON frame 不再直接抛未处理异常。
   - 2026-06-24 已补齐前端取消按钮、WebSocket cancel frame、`POST /api/runs/{run_id}/cancel` 和后端 `cancel_event` 传播；ASR、LLM、TTS provider 调用边界以及流式 delta/TTS worker 循环都会检查取消信号，取消运行返回 499 并标记为 `cancelled`。

4. 容器与启动边界
   - Dockerfile 创建非 root 用户运行应用。
   - `.dockerignore` 排除 results、deliverables、audio、env、本地 DB、模型和权重。
   - compose healthcheck 改为 `/api/ready`，provider 未就绪时容器不 ready。
   - `run_app.py` 支持 `--no-auto-port` 和 `SHIPVOICE_NO_AUTO_PORT`；容器 CMD 使用固定端口，不再静默跳端口。

补充验证命令：

```powershell
python -m py_compile run_app.py src\shipvoice\fastapi_app.py src\shipvoice\sqlite_store.py tests\test_p0_hardening.py tests\test_admin_api.py
node --check web\static\app.js
python -m unittest discover -s tests
python scripts\evaluate_retrieval.py
python scripts\evaluate_safety_gate.py --gate-only --fail-on-critical
```

## 阶段 2：重新取证与验收数据清洗（已落地）

验收目标：生成不含 ASR 污染、不含旧基座 LLM 混淆、不含“伪首音”文案的新证据包。

已完成项：

1. 真实 ASR 重跑
   - 使用 50 条录音重新跑 `scripts/evaluate_asr_online.py`。
   - 输出中不包含 `transcript_hint` 或空识别回填。
   - `results/asr_online_20260623/summary.json`：50/50 evaluated，平均 CER/WER 1.58%，术语召回 85.71%。

2. LoRA 在线链路重跑
   - 启动 LoRA 服务时强制 `SHIPVOICE_REQUIRE_LORA=1`。
   - `scripts/check_real_service_chain.py --require-lora --require-adapter-sha256 ...` 确认模型列表、provider、adapter loaded 和 adapter SHA。
   - 已产出 `results/real_chain_smoke_streaming.json` 与 `results/lora_adapter_attestation_20260623.json`，并确认 `/health` 返回 `adapter_loaded=true` 与 adapter SHA。

3. 端到端批量重跑
   - 至少 30 条真实音频样本。
   - 每条记录保存 ASR、retrieval、LLM first delta、LLM complete、TTS complete、server first audio chunk ready、server audio stream complete、total。
   - 已输出 `results/server_real_batch_baseline_20260623/summary.json` 与 `results/server_real_batch_streaming_20260623/summary.json`。
   - 已扩展到 `results/server_real_repeated_20260623/summary.json`：30 条音频 × 2 mode × 5 repeats，300/300 ok；100/100 gate-allowed 配对 streaming 更快。
   - 推荐命令：

```powershell
python scripts\run_real_chain_batch.py --env-file configs\runtime.real.env --mode baseline --limit 30 --split test --require-lora --output-dir results\server_real_batch_baseline_20260623
python scripts\run_real_chain_batch.py --env-file configs\runtime.real.env --mode streaming --limit 30 --split test --require-lora --output-dir results\server_real_batch_streaming_20260623
python scripts\compare_real_chain_batches.py --baseline results\server_real_batch_baseline_20260623\samples.jsonl --streaming results\server_real_batch_streaming_20260623\samples.jsonl
python scripts\run_real_chain_repeated.py --env-file configs\runtime.real.env --limit 30 --split test --repeats 5 --require-lora --output-dir results\server_real_repeated_20260623
```

4. 浏览器首播批量取证
   - 已生成 `results/browser_onplaying_streamable_20260623.html`。
   - 已用 Python Playwright + Chrome 批量运行，输出 `results/browser_onplaying_streamable_20260623.json` 和截图。
   - 20/20 ok；`client_audio_onplaying_ms` p50 4072 ms，p90 5600.1 ms，p95 5836.6 ms。

5. 报告再生成
   - 按用户当前要求暂不生成最终报告/PPT。
   - 后续恢复该工作时，验收报告、评测 dashboard、final report 必须只读 final manifest。

验收门槛：

- ASR 评测没有参考文本回填。
- LoRA 证据不是 base-only 响应，`served_model=shipvoice-qwen2.5-7b-lora`，`adapter_loaded=true`，且 `adapter_sha256=3462dbff405f71ed3d0b0a0d8484498a2be98ffe84ab5b2f56a2d69e7130d1cf`。
- 报告中非流式 metric source 明确为 `server_audio_payload_ready`，流式首段指标明确为 `server_first_audio_chunk_ready` 或浏览器 `audio.onplaying`。

## 阶段 3：真实流式能力升级（代码、服务器侧复验与安全闭合加固已落地）

验收目标：如果界面写“流式”，后端必须真正流式返回；浏览器端必须测量 `audio.onplaying` 后的真实首播时间。

已完成项：

1. LLM streaming
   - OpenAI-compatible provider 已增加 `stream=True` SSE 解析，读取 `choices[0].delta.content`。
   - 自建 `remote/serve_transformers_openai.py` 已增加 `TextIteratorStreamer` SSE 输出。
   - pipeline 对外发 `llm_stream_start`、`llm_first_delta`、`llm_delta`、`llm` completion 事件。

2. TTS streaming
   - pipeline 已实现句级 accumulator，句子完成后立即进入 TTS 队列。
   - TTS worker 与 LLM stream 并行，首句不等待完整回答。
   - WebSocket 已发送 `audio_chunk` 帧，包含分段 base64、seq、mime、server chunk ready time。
   - 前端已实现分段音频队列，收到首段后立即播放，后续 chunk 顺序播放。
   - 2026-06-24 已补安全闭合策略：不再按逗号软切半句；高风险问题先播保守安全前缀；每个待播片段进入 TTS 前先过输出片段 guard。
   - 2026-06-24 已把同一输出 guard 扩展到非流式完整回答，完整答案进入 TTS 前也会检查并改写无条件危险表述。

3. 浏览器计时
   - 前端继续记录真实 `<audio>.onplaying`，并把 `client_audio_onplaying_ms` 合并回 run metrics。
   - 新增指标包括 `llm_first_delta_ms`、`server_first_audio_chunk_ready_ms`、`server_audio_stream_complete_ms`、`streamed_audio_segments`。

4. Provider 连接复用
   - ASR、LLM、TTS provider 已改为持久 `httpx.Client` 连接池。
   - LLM 非流式完整回答和 `stream=true` SSE 均复用同一 provider client，不再用每次 `urlopen` 的短连接路径。
   - pipeline 增加统一 `close()`，配置热重载和应用 shutdown 时关闭旧 provider 连接池。
   - 2026-06-24 已在 `provider_status` 中补充连接池类型、keepalive、JSON/SSE 请求数、失败数、输出 guard 改写数和高风险输出标记，便于答辩时验证连接复用与输出治理。

服务器侧与浏览器复验结果：

1. 已启动 ASR、支持 SSE 的 ShipVoice LoRA LLM、TTS 服务，`/api/ready` 三项 ready。
2. 已用固定音频集重跑 baseline vs streaming：30 条 baseline + 30 条 streaming，均 30/30 ok。
3. 可回答 20 条样本中，baseline 首音频平均 7161.9 ms，streaming 首音频平均 3834.9 ms，平均提前 3327.0 ms。
4. 真实音频 WebSocket 抽样中首个 `audio_chunk` 5767 ms 到达，最终 result 11915 ms 到达。
5. 已完成 30×2×5 重复实验：300/300 ok，100/100 gate-allowed 配对 streaming 更快，平均节省 4147.39 ms。
6. 已完成浏览器 `onplaying` 批量取证：20/20 ok，p50 4072 ms，p90 5600.1 ms，p95 5836.6 ms。

验收门槛：

- `streaming` mode 首个 LLM delta 在完整答案前到达。
- TTS chunk 在完整音频生成前到达，且播报单位是安全闭合句段，不是单 token 或条件不完整半句。
- ASR/LLM/TTS provider 复用持久 HTTP client；LLM SSE 流式解析不能退回一次性短连接。
- 前端展示“浏览器开始播放”指标，不再用 server payload ready 替代。

## 阶段 4：质量与安全增强

验收目标：减少 RAG 伪命中和安全规则误放行，把评测集扩大到可答辩规模。

任务：

1. RAG 检索
   - 基于批量取证结果调优 `rag.min_score`，保留“低置信不输出 evidence”的行为。
   - citation 质量评测扩展到 100+ 问题，覆盖近义问法、错字 ASR 文本和无关问题。

2. 安全门控
   - 增加 100+ 对抗改写，覆盖 prompt injection、越权规避、危险操作细化、off-domain 混淆。
   - 继续扩展“举报/制止危险行为”和“请求执行危险行为”的边界样例，跟踪 false allow / false block。

3. ASR 后处理
   - 把硬编码术语替换迁移到配置或知识库。
   - 增加 ASR 错字变体下的 gate/RAG 联合评测。

验收门槛：

- dangerous false allow = 0。
- citation id hit@3 和 schema completeness 保持可解释。
- 低置信检索不会输出高置信 evidence。

## 阶段 5：生产化加固

验收目标：演示版可运行，生产版有明确部署边界。

任务：

1. 配置
   - 提供 `.env.example`，列出必须设置项。
   - 启动时输出缺失 provider/admin 配置的结构化诊断。

2. 存储与权限
   - 管理后台从单管理员口令升级到 RBAC。
   - SQLite 保留课程版，生产说明迁移到 PostgreSQL。

3. 监控
   - 增加 provider availability、失败率、平均 latency、blocked ratio。
   - 对 ASR/TTS/LLM endpoint 增加启动前 probe 和后台健康页告警。

验收门槛：

- 未配置管理员密码时后台不可登录。
- provider 不可用时请求 fail-closed 并记录审计错误。
- dashboard 能看到最近失败原因和 provider 健康状态。
