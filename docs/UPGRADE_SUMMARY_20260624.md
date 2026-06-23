# ShipVoice 2026-06-24 升级总结

本文档专门记录本轮围绕“真实流式低延迟、安全输出、连接复用、取消传播、前端左侧栏可用性、服务器侧复测”的升级内容、代码位置、验证结果和未测试项。

## 1. 本轮升级目标

本轮目标不是继续包装概念，而是解决答辩追问中暴露出的实际工程问题：

1. token 级增量不能直接播报，必须有安全闭合边界。
2. 流式和非流式输出都要在进入 TTS 前做输出安全检查。
3. provider 连接复用要有可观测证据，不能只口头说明。
4. 用户取消或 WebSocket 断开后，后端不能继续无边界地消耗模型资源。
5. 前端左侧“快速场景”和“高级选项”展开空间必须足够可读。
6. 服务器侧要尽量做真实 E2E 复测；若因环境不可达无法测，必须明确记录。

## 2. 已完成升级

### 2.1 非流式完整回答输出 guard

已完成。

以前主要加固的是 `streaming` 路径的待播片段。现在非流式完整回答在进入 TTS 前也会经过输出 guard。

代码位置：

- `src/shipvoice/pipeline.py`
  - `_guard_complete_answer`
  - `_guard_output_segment`
  - `_is_explicitly_safe_risky_sentence`

行为：

- 对高风险问题先补安全前缀。
- 对“可以进入”“可以继续”“关闭报警”“跳过审批”等无条件危险表达进行改写。
- 对“必须先完成审批、通风、测氧测爆和监护确认后方可进入”这类带完整前置条件的句子不误杀。
- `provider_status` 记录 `output_guard_rewrites` 和 `high_risk_output`。

### 2.2 流式安全闭合播报加强

已完成。

代码位置：

- `src/shipvoice/pipeline.py`
  - `_run_streaming_llm_tts`
  - `_pop_stream_sentence`
  - `_guard_stream_segment`

行为：

- 不再按逗号切半句。
- LLM SSE delta 只作为传输单位。
- 播报单位是句号、问号、感叹号、分号等闭合边界后的安全句段。
- 高风险场景先排入保守安全前缀。
- 每个待播片段进入 TTS worker 前都经过输出 guard。

### 2.3 provider 连接复用与可观测性

已完成。

代码位置：

- `src/shipvoice/providers.py`
  - `HttpJsonASRProvider`
  - `OpenAICompatibleLLMProvider`
  - `HttpJsonTTSProvider`
  - `_post_json_with_pool`
- `src/shipvoice/pipeline.py`
  - `_provider_observability_status`

行为：

- ASR、LLM、TTS provider 复用持久 `httpx.Client`。
- LLM 完整回答请求和 `stream=true` SSE 请求复用同一 provider client。
- provider 记录 JSON 请求数、SSE 请求数和失败数。
- pipeline 关闭或配置热重载时关闭旧 provider client。

可观测字段示例：

```text
asr_http_client
asr_http_keepalive
asr_http_requests
asr_http_failures
llm_http_client
llm_http_requests
llm_http_stream_requests
llm_http_failures
tts_http_client
tts_http_requests
tts_http_failures
```

### 2.4 运行取消传播

已完成。

代码位置：

- `src/shipvoice/fastapi_app.py`
  - `POST /api/runs/{run_id}/cancel`
  - WebSocket cancel frame listener
  - run-level `threading.Event`
- `src/shipvoice/pipeline.py`
  - `PipelineCancelled`
  - ASR 后、检索前后、LLM/TTS 前后、流式 delta 循环、TTS worker 循环中的取消检查
- `src/shipvoice/providers.py`
  - ASR/LLM/TTS provider 调用边界的 `cancel_event` 检查
- `web/static/app.js`
  - `cancelActiveRun`
  - `requestServerCancel`
  - WebSocket `{ "type": "cancel" }`

行为：

- 前端运行中显示“取消”按钮。
- HTTP 路径调用 `POST /api/runs/{run_id}/cancel`。
- WebSocket 路径发送 `{ "type": "cancel" }` 控制帧。
- 后端设置运行级 `cancel_event`。
- 被取消的运行返回 499，并记录为 `cancelled`。

### 2.5 前端左侧栏展开空间修复

已完成。

代码位置：

- `web/static/index.html`
- `web/static/styles.css`
- `web/static/app.js`

行为：

- 左侧栏桌面端固定高度并支持内部滚动。
- 快速场景列表展开高度从原先很小提升到视口相关高度。
- 高级选项展开时不被挤压。
- 快速场景列表内部可滚动。
- 新增运行中“取消”按钮。

布局验证截图：

```text
results/final_acceptance_20260624/frontend-sidebar-expanded-desktop.png
results/final_acceptance_20260624/frontend-sidebar-expanded-mobile.png
```

### 2.6 文档同步

已完成。

已更新：

- `ShipVoice_A2_更新版全仓Bug审计与升级执行文档_20260622.md`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/PHASE1_SCORECARD.md`
- `docs/UPGRADE_EXECUTION_PLAN_20260622.md`
- `docs/RUNBOOK.md`
- `docs/OPERATIONS_RUNBOOK.md`
- `docs/SHIPVOICE_USER_MANUAL.md`

重点改动：

- 删除“取消传播仍未完成”的旧说法。
- 增加完整回答输出 guard。
- 增加 provider 连接复用和可观测字段说明。
- 增加取消接口和 WebSocket cancel frame 说明。
- 记录前端左侧栏展开空间修复。

## 3. 本地验证结果

以下验证已执行并通过。

### 3.1 Python 编译检查

```powershell
python -m py_compile src\shipvoice\providers.py src\shipvoice\pipeline.py src\shipvoice\fastapi_app.py tests\test_p0_hardening.py tests\test_admin_api.py
```

结果：通过。

### 3.2 核心单元测试

```powershell
python -m unittest tests.test_p0_hardening tests.test_admin_api
```

结果：31 个测试通过。

### 3.3 全量单元测试

```powershell
python -m unittest discover -s tests
```

结果：40 个测试通过。

### 3.4 前端 JS 语法检查

```powershell
node --check web\static\app.js
```

结果：通过。

### 3.5 项目 quick validation

```powershell
python scripts\validate_project.py --quick
```

结果：通过。

注意：该脚本会重建部分训练集、评测结果、dashboard 和报告文件，这是仓库原有验证脚本行为。

### 3.6 FastAPI 本地 smoke

```powershell
python scripts\smoke_fastapi_backend.py --env-file configs\runtime.real.env --skip-live-run
```

结果：通过。

说明：这里跳过了真实 ASR/LLM/TTS live run，因为本机 provider 端口未通。

### 3.7 前端布局验证

使用 Python Playwright 离线渲染并检查桌面/移动端布局。

验证结果：

- 桌面端 `.sidebar` 为 `overflow-y: auto`。
- 桌面端左侧栏内容超出时可滚动。
- 快速场景展开列表高度约 499 px。
- 移动端快速场景展开列表高度约 439 px。
- 取消按钮可见，按钮行高度正常。
- 已保存桌面和移动端截图。

结果：通过。

## 4. 服务器侧复测尝试

本轮尝试连接之前配置的服务器：

```text
ssh -p 48359 root@connect.westc.seetacloud.com
```

实际结果：

- DNS 解析成功：`connect.westc.seetacloud.com -> 116.172.66.186`
- `connect.westc.seetacloud.com:48359` TCP 不通
- SSH 报错：`Connection refused`
- 本地隧道端口均不通：

```text
127.0.0.1:18001 tcp=False
127.0.0.1:18002 tcp=False
127.0.0.1:18034 tcp=False
```

本地应用 readiness 结果：

```text
/api/live  = 200
/api/health = 200
/api/ready = 503
```

`/api/ready` 的 503 原因是 ASR、LLM、TTS 三个真实 provider endpoint 都连接失败：

```text
ASR: http://127.0.0.1:18001/asr unreachable
LLM: http://127.0.0.1:18034/v1 unreachable
TTS: http://127.0.0.1:18002/tts unreachable
```

结论：这不是私钥或密码错误。连接在 SSH 认证前已经被目标端口拒绝，说明 SeeTaCloud 当前 SSH 映射端口不可用或已变化。

## 5. 最后：未测试或未能测试的内容

以下内容没有被标记为通过。

1. 服务器真实 E2E 没有完成。

原因：`connect.westc.seetacloud.com:48359` TCP refused，无法 SSH 登录，无法启动远端 ASR/LLM/TTS 服务，也无法建立本地 18001/18002/18034 隧道。

2. 真实 ASR + ShipVoice LoRA LLM + 真实 TTS live run 没有完成。

原因：本地 provider 端口未通，`scripts/check_real_service_chain.py` 失败，`/api/ready` 返回 503。

3. 远端服务启动、停止和 shutdown 没有执行。

原因：SSH 端口不可达，不能安全进入远端机器执行 `remote/start_full_lora_stack.sh`、`remote/stop_full_lora_stack.sh` 或 `shutdown -h now`。

4. 带真实 provider 的 WebSocket audio_chunk 现场链路没有本轮重跑。

原因：真实 ASR/LLM/TTS provider 不在线。已验证代码级流式、TTS chunk、output guard 和取消逻辑的单元测试，但没有本轮服务器现场 E2E。

5. 浏览器在线页面对真实接口的完整人工交互没有完成。

原因：真实 provider 未通。已完成离线布局渲染和截图验证，以及后端 skip-live smoke；未完成带真实模型响应的浏览器端整链路人工点击演示。

6. 后台评测任务队列、远端认证、依赖锁、provider 分级 deadline、持久队列仍属于长期工程化项。

这些不是本轮 6 个问题的阻断项，但仍未完成生产化升级。
