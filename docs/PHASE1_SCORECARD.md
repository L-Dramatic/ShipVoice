# ShipVoice 阶段验收表

## 当前状态

ShipVoice 已从课程原型升级为真实 provider 链路应用。现行验收重点如下：

| 项目 | 状态 | 证据 |
|---|---|---|
| 前后端应用 | 已完成 | `run_app.py`, `src/shipvoice/fastapi_app.py`, `web/static/` |
| 浏览器录音和音频上传 | 已完成 | `web/static/app.js` |
| 真实 ASR 接入 | 已实现接口 | `HttpJsonASRProvider`, `configs/runtime.real.env` |
| 真实 LLM 接入 | 已实现接口 | `OpenAICompatibleLLMProvider` |
| 真实 TTS 接入 | 已实现接口 | `HttpJsonTTSProvider` |
| 安全门控 | 已完成 | `KeywordSafetyGate`, `results/safety_gate_eval_summary.json` |
| RAG 证据引用 | 已完成 | `data/knowledge/`, `results/citation_quality_summary.json` |
| 后台审计 | 已完成 | `src/shipvoice/sqlite_store.py`, `web/static/admin.html` |

## 验收原则

真实 ASR、LLM、TTS 服务缺失时，问答请求必须失败并记录错误。文本输入可以用于 typed input 测试，但不能替代音频 ASR 证据。

## 下一步

1. 启动 GPU 真实服务。
2. 运行 `scripts/check_real_service_chain.py`。
3. 用 30 条以上录音重采集真实端到端指标。
4. 更新报告和 PPT 中的最终延迟表。
