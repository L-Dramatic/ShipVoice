# ShipVoice 容器部署说明

容器仅负责运行 FastAPI 应用和前端静态资源。ASR、LLM、TTS 必须由真实外部服务提供。

## 配置

`docker-compose.app.yml` 使用：

```text
configs/runtime.real.env
```

启动前请确认该文件中的 ASR、LLM、TTS endpoint 在容器网络内可访问。

## 启动

```powershell
docker compose -f docker-compose.app.yml up --build
```

访问：

```text
http://127.0.0.1:8022/
```

## 注意

如果 provider 端点不可达，应用可以启动，但问答请求会失败并在后台审计日志中记录错误。这是预期行为。
