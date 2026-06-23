# ShipVoice 阶段验收表

## 当前状态

ShipVoice 已从课程原型升级为真实 provider 链路应用。现行验收重点如下：

| 项目 | 状态 | 证据 |
|---|---|---|
| 前后端应用 | 已完成 | `run_app.py`, `src/shipvoice/fastapi_app.py`, `web/static/` |
| 浏览器录音和音频上传 | 已完成 | `web/static/app.js` |
| 真实 ASR 接入 | 已在线复验 | `HttpJsonASRProvider`, `configs/runtime.real.env`, `/api/ready` |
| 真实 LLM 接入 | 已在线复验 | `OpenAICompatibleLLMProvider`, `served_model=shipvoice-qwen2.5-7b-lora`, `adapter_loaded=true` |
| 真实 TTS 接入 | 已在线复验 | `HttpJsonTTSProvider`, `/api/ready` |
| Provider 连接复用 | 已完成 | ASR/LLM/TTS provider 使用持久 `httpx.Client` 连接池；LLM SSE 与普通 JSON 请求复用同一 client |
| Provider 可观测性 | 已完成 | `provider_status` 暴露连接池类型、keepalive、JSON/SSE 请求数、失败数和输出 guard 改写数 |
| 流式低延迟链路 | 已完成重复实验、浏览器首播取证和安全闭合播报加固 | `OpenAICompatibleLLMProvider.stream_answer`, `ShipVoicePipeline._run_streaming_llm_tts`, 输出片段 guard, WebSocket `audio_chunk`, `results/server_real_repeated_20260623/summary.json`, `results/browser_onplaying_streamable_20260623.json` |
| 完整回答输出护栏 | 已完成 | 非流式完整回答进入 TTS 前同样执行输出 guard；危险无条件表述会被安全模板改写 |
| 运行取消传播 | 已完成 | 前端取消按钮、WebSocket cancel frame、`POST /api/runs/{run_id}/cancel`、pipeline/provider `cancel_event` 传播与 499 cancelled 状态 |
| LoRA adapter attestation | 已完成 | `results/lora_adapter_attestation_20260623.json`, `adapter_sha256=3462dbff405f71ed3d0b0a0d8484498a2be98ffe84ab5b2f56a2d69e7130d1cf` |
| 在线 ASR 质量评测 | 已完成 | `results/asr_online_20260623/summary.json`：50/50 evaluated，平均 CER/WER 1.58%，术语召回 85.71% |
| 安全门控 | 已完成 | `KeywordSafetyGate`, `results/safety_gate_eval_summary.json` |
| RAG 证据引用 | 已完成 | `data/knowledge/`, `results/citation_quality_summary.json` |
| 后台审计 | 已完成 | `src/shipvoice/sqlite_store.py`, `web/static/admin.html` |

## 验收原则

真实 ASR、LLM、TTS 服务缺失时，问答请求必须失败并记录错误。文本输入可以用于 typed input 测试，但不能替代音频 ASR 证据。当前 2026-06-23 服务器侧复验、30×2×5 重复实验、LoRA adapter SHA、在线 ASR 评测和浏览器 `audio.onplaying` 批量表均已完成；后续又补充了流式播报安全闭合策略、完整回答输出 guard、provider HTTP 连接池复用、provider 请求计数和运行取消传播：token 只作为传输单位，高风险问题先播安全前缀，待播片段和完整回答进入 TTS 前经过输出 guard，ASR/LLM/TTS 调用不再每次临时创建 HTTP 连接，用户取消后不继续生成或播报。最终答辩材料后续只需从同一 manifest 生成。

## 剩余事项

1. 基于最终证据重建 final manifest，并在报告/PPT恢复制作时只读该 manifest。
2. 更新报告和 PPT 中的最终首播延迟表。
3. 继续做生产化长期项：持久队列、依赖锁、远端认证、容器加固和故障恢复演练。
