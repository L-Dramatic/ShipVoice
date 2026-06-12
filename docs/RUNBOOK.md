# ShipVoice 运行手册

## 1. 启动本地 mock 应用

```powershell
.\scripts\start_shipvoice_app.ps1 -Mode mock
```

默认地址：

```text
http://127.0.0.1:8022
```

## 2. 启动本地 real 应用

先准备：

```powershell
Copy-Item configs\runtime.real.env.example configs\runtime.real.env
```

或：

```powershell
Copy-Item configs\runtime.vllm.env.example configs\runtime.real.env
```

然后启动：

```powershell
.\scripts\start_shipvoice_app.ps1 -Mode real
```

## 3. 构建知识库索引

```powershell
python scripts\build_knowledge_index.py
```

输入：

```text
data\knowledge\ship_safety_corpus.jsonl
```

输出：

```text
data\knowledge\ship_safety_index.json
```

## 4. 检索评测

```powershell
python scripts\evaluate_retrieval.py
```

## 5. 单条问题调试

```powershell
python scripts\run_single.py "舾装阶段管路试压有哪些安全风险？" --mode full
```

## 6. 真实链路检查

```powershell
python scripts\check_real_service_chain.py --env-file configs\runtime.real.env --sample-id A001
```

输出：

```text
results\real_chain_smoke.json
```

检查项包括：

1. ASR `/health`
2. TTS `/health`
3. LLM `/v1/models`
4. 一条真实录音是否能跑通
5. 本地 pipeline 是否真的走了真实 provider

## 7. 全项目 quick validation

```powershell
python scripts\validate_project.py --quick
```

## 8. 全项目 full validation

```powershell
python scripts\validate_project.py --full
```

## 9. 容器方式启动

```powershell
docker compose -f docker-compose.app.yml up --build
```

## 10. 远程 GPU 服务

ASR / TTS：

```bash
bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
bash remote/stop_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

LLM / vLLM：

```bash
bash remote/start_vllm_llm.sh /root/autodl-tmp/shipvoice
bash remote/stop_vllm_llm.sh /root/autodl-tmp/shipvoice
```
