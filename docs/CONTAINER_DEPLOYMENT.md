# ShipVoice 容器化部署

## 目标

这套容器化配置主要服务两个场景：

1. 向老师或评委证明这不是一次性脚本，而是可部署应用
2. 让团队成员在不同机器上用统一方式启动后端

## 文件

- `Dockerfile`
- `.dockerignore`
- `docker-compose.app.yml`

## 直接启动

```powershell
docker compose -f docker-compose.app.yml up --build
```

默认行为：

- 使用 `configs/runtime.mock.env`
- 暴露 `8022`
- 挂载 `data/`、`results/`、`configs/`

启动后访问：

```text
http://127.0.0.1:8022/
http://127.0.0.1:8022/admin.html
```

## 切到真实 provider

把 `docker-compose.app.yml` 里的：

```yaml
env_file:
  - ./configs/runtime.mock.env
```

改成：

```yaml
env_file:
  - ./configs/runtime.real.env
```

前提是你已经准备好 `configs/runtime.real.env`，并填入真实 ASR / LLM / TTS 地址。

## 健康检查

compose 自带 `healthcheck`，检查：

```text
/api/health
```

这意味着容器不是“进程活着就算成功”，而是后端接口真的起来才算成功。

## 说明

这份容器配置当前只覆盖应用后端，不覆盖远程 GPU 上的 ASR / TTS 服务。

原因很实际：

1. 真实语音模型服务通常跑在独立 GPU 机器
2. 课程项目当前更需要证明应用层部署能力
3. 把 GPU 服务和应用前端后端解耦，架构上也更合理
