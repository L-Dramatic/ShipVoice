# ShipVoice 真链路部署说明

## 目标

这份文档解决三件事：

1. 远程 GPU 机器启动真实 ASR / TTS / LLM 服务
2. 本地 FastAPI 应用切换到真实 provider
3. 用统一脚本检查整条链路是否真的打通

## 关键文件

- `remote/start_shipvoice_real_services.sh`
- `remote/stop_shipvoice_real_services.sh`
- `remote/start_vllm_llm.sh`
- `remote/stop_vllm_llm.sh`
- `configs/runtime.mock.env`
- `configs/runtime.real.env.example`
- `configs/runtime.vllm.env.example`
- `scripts/start_shipvoice_app.ps1`
- `scripts/check_real_service_chain.py`
- `Dockerfile`
- `docker-compose.app.yml`

## Step 1：远程机器启动真实 ASR / TTS

在 AutoDL 机器上进入项目目录后执行：

```bash
bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

默认会启动：

- ASR: `http://<server-ip>:8001/asr`
- TTS: `http://<server-ip>:8002/tts`

脚本会自动等待两个 `/health` 接口成功，不再是盲启。

### 切换 TTS 后端

`edge-tts`：

```bash
TTS_BACKEND=edge bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

`gtts`：

```bash
TTS_BACKEND=gtts bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

`ChatTTS`：

```bash
HF_ENDPOINT=https://hf-mirror.com CHATTTS_SOURCE=huggingface TTS_BACKEND=chattts bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

### 停止远程 ASR / TTS

```bash
bash remote/stop_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

## Step 2：远程机器启动真实 LLM（vLLM）

优先建议用 vLLM 启动一个 OpenAI-compatible LLM 服务：

```bash
bash remote/start_vllm_llm.sh /root/autodl-tmp/shipvoice
```

默认参数：

- Base URL: `http://<server-ip>:11434/v1`
- Model: `Qwen/Qwen2.5-7B-Instruct`

脚本会自动等待：

```text
/v1/models
```

返回成功后才算 LLM 真正可用。

### 停止远程 LLM

```bash
bash remote/stop_vllm_llm.sh /root/autodl-tmp/shipvoice
```

## Step 3：本地准备真实运行配置

如果你要手工配置，可以复制：

```powershell
Copy-Item configs\runtime.real.env.example configs\runtime.real.env
```

然后填写真实地址：

```text
SHIPVOICE_ASR_ENDPOINT=http://<server-ip>:8001/asr
SHIPVOICE_OPENAI_BASE_URL=http://<llm-host>:11434/v1
SHIPVOICE_LLM_MODEL=qwen2.5:7b-instruct
SHIPVOICE_TTS_ENDPOINT=http://<server-ip>:8002/tts
```

如果你准备用远程 vLLM，可以直接从模板复制：

```powershell
Copy-Item configs\runtime.vllm.env.example configs\runtime.real.env
```

如果暂时没有真实 LLM，也可以保留：

```text
SHIPVOICE_LLM_PROVIDER=mock
```

这样系统会变成“真实 ASR + RAG + mock LLM + 真实 TTS”的半真实链路。

## Step 4：本地启动应用

### mock 模式

```powershell
.\scripts\start_shipvoice_app.ps1 -Mode mock
```

### real 模式

```powershell
.\scripts\start_shipvoice_app.ps1 -Mode real
```

也可以显式指定：

```powershell
python run_app.py --env-file configs\runtime.real.env --port 8023
```

## Step 5：检查真链路是否真的打通

```powershell
python scripts\check_real_service_chain.py --env-file configs\runtime.real.env --sample-id A001
```

输出文件：

```text
results\real_chain_smoke.json
```

它会检查：

1. ASR `/health`
2. TTS `/health`
3. LLM `/v1/models`
4. 一条真实录音能否走通 ASR
5. 本地 pipeline 是否真的用了配置中的真实 provider

## Step 6：在后台确认当前运行状态

启动应用后打开：

```text
http://127.0.0.1:8022/admin.html
```

重点看两个面板：

1. `后端配置`
   - 检查当前配置和环境变量是否生效

2. `Provider 健康`
   - 检查 ASR / LLM / TTS 是 `mock` 还是真服务
   - 如果配置了 HTTP endpoint，会显示是否 `reachable`
   - 对 LLM 还会检查 `/models` 和目标模型是否存在

## 推荐演示方式

课程答辩时建议准备两套模式：

1. `mock` 稳定演示模式
   - 响应稳定
   - 用于现场保底

2. `real` 能力展示模式
   - 展示真实 ASR / LLM / TTS 接入
   - 配合后台 `Provider 健康` 证明不是纯前端演示

## 最小可交付标准

至少做到下面五点，项目就不再只是网页 demo：

1. 后台能显示 provider 健康状态
2. 本地应用能通过 env 文件切换 mock / real
3. 远程 ASR / TTS 有统一启动与停止脚本
4. 远程 LLM 有统一启动与停止脚本
5. `scripts/check_real_service_chain.py` 能产出可保存的冒烟结果
