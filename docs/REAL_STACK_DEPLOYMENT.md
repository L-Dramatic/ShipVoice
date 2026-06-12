# ShipVoice 真链路部署说明

## 目标

这份文档解决三件事：

1. 远程 GPU 机器启动真实 ASR / TTS 服务
2. 本地 FastAPI 应用切换到真实 provider
3. 用统一脚本检查整条链路是否真的打通

## 目录里的关键文件

- `remote/start_shipvoice_real_services.sh`
- `remote/stop_shipvoice_real_services.sh`
- `configs/runtime.mock.env`
- `configs/runtime.real.env.example`
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

脚本现在会自动等待两个 `/health` 接口成功，不再是盲启。

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

### 停止远程服务

```bash
bash remote/stop_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

这个脚本现在会先正常 `kill`，若进程未退出再强制结束。

## Step 2：本地准备真实运行配置

复制模板：

```powershell
Copy-Item configs\runtime.real.env.example configs\runtime.real.env
```

然后把 `configs/runtime.real.env` 里的这些值改成真实地址：

```text
SHIPVOICE_ASR_ENDPOINT=http://<server-ip>:8001/asr
SHIPVOICE_OPENAI_BASE_URL=http://<llm-host>:11434/v1
SHIPVOICE_LLM_MODEL=qwen2.5:7b-instruct
SHIPVOICE_TTS_ENDPOINT=http://<server-ip>:8002/tts
```

如果暂时没有真实 LLM，也可以保留：

```text
SHIPVOICE_LLM_PROVIDER=mock
```

这样系统会变成“真实 ASR + RAG + mock LLM + 真实 TTS”的半真实链路。

## Step 3：本地启动应用

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

## Step 4：检查真链路是否真的打通

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
3. 一条真实录音能否走通 ASR
4. 本地 pipeline 是否真的用了 `http_json` provider

## Step 5：在后台确认当前运行状态

启动应用后打开：

```text
http://127.0.0.1:8022/admin.html
```

看两个位置：

1. `后端配置`
   - 检查当前配置和环境变量是否生效

2. `Provider 健康`
   - 检查 ASR / LLM / TTS 是 `mock` 还是真服务
   - 若配置了 HTTP endpoint，会显示是否 `reachable`

## 推荐演示方式

课程答辩时建议准备两套模式：

1. `mock` 稳定演示模式
   - 响应稳定
   - 用于现场保证不翻车

2. `real` 能力展示模式
   - 展示真实 ASR / TTS 接入
   - 配合后台 `Provider 健康` 证明不是纯前端演示

## 最小可交付标准

至少做到下面四点，项目就不再只是网页 demo：

1. 后台能显示 provider 健康状态
2. 本地应用能通过 env 文件切换 mock / real
3. 远程真服务有统一启动与停止脚本
4. `scripts/check_real_service_chain.py` 能产出可保存的冒烟结果
