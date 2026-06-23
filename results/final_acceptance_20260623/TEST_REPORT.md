# ShipVoice 最终验收测试报告（2026-06-23）

## 1. 验收目标

本轮验收按“课程高分交付 + 真实系统边界”的标准执行，重点不是证明页面能打开，而是确认系统在没有真实 provider 时不会伪造答案或音频，在危险或越界输入下能够 fail-closed，并且前端不会留下明显的演示包装、假数据或视觉错位。

验收对象包括：

- FastAPI 后端、Pipeline、安全门控、RAG/Provider 调用边界。
- 用户端前端：文本输入、录音/上传入口、结果区、引用区、运行详情、响应式布局。
- 管理端前端：认证边界、后台入口、未登录状态、知识库和运行审计页面。
- 测试、静态检查、API 边界、视觉截图和 mock/理想化风险审计。

## 2. 当前运行环境

- 本地应用地址：`http://127.0.0.1:8026/`
- 后端启动方式：`python run_app.py --env-file configs\runtime.real.env --port 8026`
- 当前 provider 配置：
  - ASR：`http_json_asr`
  - LLM：`openai_compatible:shipvoice-qwen2.5-7b-lora`
  - TTS：`http_json_tts`
- 当前本机没有可达 GPU provider：正常领域问题会真实报错，不生成替代答案。
- 当前未设置 `SHIPVOICE_ADMIN_PASSWORD`：后台处于 `missing_password`，未认证时禁止访问后台数据。

## 3. 已执行测试结果

| 类别 | 命令或证据 | 结果 | 说明 |
|---|---|---:|---|
| Python 单元/集成测试 | `python -m pytest tests -q` | 通过 | 32 passed，147 个依赖库 deprecation warnings，不影响功能 |
| 前端 JS 语法 | `node --check web\static\app.js`、`node --check web\static\admin.js` | 通过 | 无语法错误 |
| Python 语法 | `python -m py_compile ...` | 通过 | 已覆盖 `run_app.py`、`src/shipvoice`、`scripts` |
| 安全门控评测 | `python scripts\evaluate_safety_gate.py --gate-only --fail-on-critical` | 通过 | 56/56 PASS，false allow 为 0 |
| Git 空白检查 | `git diff --check` | 通过 | 仅有 Windows LF/CRLF 提示 |
| 管理端鉴权 | `api_admin_security_checks.json` | 通过 | 状态 200；未登录 session/knowledge 为 401；未配置密码登录为 503 |
| 安全拒答 API | `api_safety_refusal_after_restart.json` | 通过 | 股票、诗歌、绕过安全检查均被门控拦截，LLM/TTS 未调用 |
| 真实 provider 不可达 | `api_domain_real_provider_unavailable.json` | 通过 | 正常领域问题在 LLM 不可达时返回 500，不生成假回答 |
| 桌面视觉 | `07-main-after-fixes.png`、`08-admin-after-fixes.png` | 通过 | 页面非空白、主控件可见、无明显遮挡 |
| 窄屏视觉 | `09-main-narrow-520-after-fixes.png` | 通过 | 首屏控件不横向溢出，按钮文字未挤压 |

## 4. 本轮发现并修复的问题

### 4.1 安全门控拦截后仍可能依赖 TTS

问题：门控已经拒绝的请求，本质上不需要语音合成。如果 TTS provider 不可达，旧逻辑可能把一次正确拒答变成接口失败。

修复：门控拒绝后直接跳过 LLM 和 TTS，返回 `tts=not_called_safety_gate`、`timing_source=safety_gate_no_audio`，并确保没有音频 payload。

影响：危险请求、越界问题、prompt injection 在真实 provider 不可达时仍能稳定 fail-closed，不会因为 TTS 失败影响拒答。

### 4.2 门控拒答的运行画像不够准确

问题：纯文本门控拒答曾被标记为 `real_text`，容易让审计人员误以为系统完成了真实 LLM/TTS 链路。

修复：当 `llm_provider=not_called` 时优先标记为 `real_guarded`。

影响：审计记录更准确，能区分“真实安全门控拒答”和“完整真实模型链路回答”。

### 4.3 音频二次播放可能停在结束位置

问题：浏览器音频第一次播放结束后，第二次播放可能因为 `currentTime` 仍在末尾而无声。

修复：非流式 TTS 音频加载后重置 `currentTime`，播放事件中如果发现 ended 状态也重置到 0，流式队列播放结束后同样复位。

影响：降低答辩时“第一次有声音、第二次没声音”的风险。完整真实 TTS 二次播放仍建议在 GPU provider 打开后再复测。

### 4.4 前端存在容易被误解为假数据的视觉元素

问题：音频可视化在 Web Audio 初始化失败时会画模拟波形；雷达背景有固定的 `Sec-A / Zone-3 / Dock-1` 目标点。这些不是模型结果，但看起来像真实信号或现场监控数据。

修复：Web Audio 初始化失败时隐藏可视化，不再模拟波形；雷达背景只保留扫描线，不再显示固定目标点。

影响：产品运行界面不再用假波形或假目标增强观感，减少答辩时被追问“这些数据从哪里来”的风险。

### 4.5 窄屏布局防护不足

问题：移动端/窄屏下存在潜在横向溢出风险。

修复：补充 520px 以下宽度约束，对输入区、按钮、录音区、折叠面板和侧栏卡片做 `max-width` 和 `overflow-x` 保护。

影响：窄屏首屏截图通过视觉验收。

## 5. Mock / 理想化风险审计

### 5.1 产品运行代码

对 `src`、`web`、`configs` 执行关键词复查：`mock`、`fake`、`simulation`、`simulate`、`Fallback`、`Sec-A`、`Zone-3`、`Dock-1`、`假`、`模拟`。当前产品运行代码未发现命中。

当前行为符合 real-only 原则：

- 门控拒绝：不调用 LLM/TTS，不生成假音频。
- 正常领域问题但 provider 不可达：返回真实错误，不生成替代答案。
- 后台未配置密码：不开放后台数据。

### 5.2 测试代码

`tests` 中仍然有 `FakeASR`、`FakeLLM`、`FakeTTS`。这是测试隔离用的假对象，不参与运行时，不属于产品 mock。答辩时如果被问到，可以说明：真实运行由 `configs/runtime.real.env` 的 provider 决定，测试里的 fake 只用于单元测试验证边界逻辑。

### 5.3 文档与提交材料

部分历史文档和脚本中仍有“demo/演示/可降级”等措辞。它们不是运行时代码，但最终提交前应统一口径：

- 可以说“答辩演示”或“课程演示流程”。
- 不应说“无 GPU 时也可以跑通回答和指标”。
- 应统一为“无真实 provider 时系统失败并记录错误，不生成替代答案或假音频”。

## 6. 尚未完成的 GPU 真链路验收

本轮是在本地真实应用 + 不可达 provider 状态下完成的验收，已经证明 fail-closed 和 no-mock 边界。但以下项目必须在 AutoDL/GPU 服务打开后再验收：

- 真实音频上传或浏览器录音后的 ASR 转写。
- 真实 LLM/LoRA 回答质量、RAG 引用条目是否准确。
- 真实 TTS 音频生成、首音频延迟、二次播放是否稳定。
- 流式低延迟模式下 WebSocket `audio_chunk`、浏览器 `audio.onplaying` 首播打点。
- 后台 Provider Health 显示真实服务可达。

## 7. 结论

当前版本已经通过本地软件验收的核心项：代码测试、静态检查、安全门控、拒答边界、后台认证边界、真实 provider 不可达时不伪造结果、桌面和窄屏视觉检查。

如果只看“没有 GPU 的本地应用质量”，当前版本可以作为答辩前收尾版本继续准备 PPT 和手册；如果要声明“真实端到端语音链路完全可用”，还必须在 GPU 打开后完成第 6 节的真链路复测，并把结果追加到本报告。
