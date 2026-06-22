from __future__ import annotations

import argparse
import json
import importlib.util
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.config import load_env_file  # noqa: E402


def find_free_port(preferred: int = 8035) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"no free port found from {preferred} to {preferred + 19}")


def get_json(url: str, timeout: int = 60, token: str | None = None) -> dict:
    headers = {}
    if token:
        headers["X-Admin-Token"] = token
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict, timeout: int = 60, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Admin-Token"] = token
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def delete_json(url: str, timeout: int = 60, token: str | None = None) -> dict:
    headers = {}
    if token:
        headers["X-Admin-Token"] = token
    request = urllib.request.Request(url, headers=headers, method="DELETE")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def read_log_tail(path: Path, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


def parse_logged_base_url(log_text: str) -> str:
    match = re.search(r"(?:ShipVoice FastAPI:|Uvicorn running on)\s+(http://[^\s]+)", log_text)
    return match.group(1).rstrip("/") if match else ""


def wait_until_ready(
    base_url: str,
    timeout_s: int = 45,
    *,
    process: subprocess.Popen | None = None,
    log_path: Path | None = None,
) -> dict:
    deadline = time.time() + timeout_s
    last_error = ""
    urls = [base_url.rstrip("/")]
    while time.time() < deadline:
        if log_path:
            logged_url = parse_logged_base_url(read_log_tail(log_path))
            if logged_url and logged_url not in urls:
                urls.insert(0, logged_url)
        for candidate in list(urls):
            try:
                health = get_json(f"{candidate}/api/health", timeout=5)
                health["_base_url"] = candidate
                return health
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                last_error = f"{candidate}: {exc}"
        if process is not None and process.poll() is not None:
            log_tail = read_log_tail(log_path) if log_path else ""
            raise RuntimeError(
                f"fastapi app exited before ready with code {process.returncode}: {last_error}\n{log_tail}"
            )
        time.sleep(1)
    log_tail = read_log_tail(log_path) if log_path else ""
    raise RuntimeError(f"fastapi app did not become ready: {last_error}\n{log_tail}")


def websocket_smoke_python(port: int) -> dict:
    code = f"""
import asyncio
import json
import websockets

async def main():
    seen = []
    async with websockets.connect('ws://127.0.0.1:{port}/ws/run') as ws:
        await ws.send(json.dumps({{
            'session_id': 'smoke-fastapi',
            'question': '密闭舱室动火作业前需要完成哪些安全确认？',
            'mode': 'full',
            'history': []
        }}, ensure_ascii=False))
        while True:
            payload = json.loads(await ws.recv())
            seen.append(payload.get('type'))
            if payload.get('type') == 'error':
                raise RuntimeError(json.dumps(payload, ensure_ascii=False))
            if payload.get('type') == 'result':
                print(json.dumps({{
                    'types': seen,
                    'gate': payload['result']['gate']['label'],
                    'total_ms': payload['result']['metrics']['total_ms']
                }}, ensure_ascii=False))
                return

asyncio.run(asyncio.wait_for(main(), timeout=30))
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(result.stdout.strip())


def websocket_smoke_node(port: int) -> dict:
    code = f"""
const ws = new WebSocket('ws://127.0.0.1:{port}/ws/run');
const seen = [];
ws.addEventListener('open', () => {{
  ws.send(JSON.stringify({{
    session_id: 'smoke-fastapi',
    question: '密闭舱室动火作业前需要完成哪些安全确认？',
    mode: 'full',
    history: []
  }}));
}});
ws.addEventListener('message', (event) => {{
  const payload = JSON.parse(String(event.data));
  seen.push(payload.type);
  if (payload.type === 'result') {{
    console.log(JSON.stringify({{
      types: seen,
      gate: payload.result.gate.label,
      total_ms: payload.result.metrics.total_ms
    }}));
    ws.close();
  }}
  if (payload.type === 'error') {{
    console.error(JSON.stringify(payload));
    process.exit(1);
  }}
}});
ws.addEventListener('close', () => process.exit(0));
setTimeout(() => process.exit(2), 30000);
"""
    result = subprocess.run(["node", "-e", code], cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(result.stdout.strip())


def websocket_smoke(port: int) -> dict:
    if importlib.util.find_spec("websockets"):
        return websocket_smoke_python(port)
    if not shutil.which("node"):
        raise RuntimeError("WebSocket smoke requires Python package 'websockets' or a Node.js runtime.")
    return websocket_smoke_node(port)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the ShipVoice FastAPI backend.")
    parser.add_argument(
        "--base-port",
        type=int,
        default=8035,
        help="First local port to try when starting a temporary backend.",
    )
    parser.add_argument(
        "--skip-live-run",
        action="store_true",
        help="Skip /ws/run end-to-end inference. Use this when ASR/LLM/TTS GPU services are offline.",
    )
    parser.add_argument("--env-file", default="", help="Load real provider environment before starting the app.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    port = find_free_port(args.base_port)
    env = os.environ.copy()
    env["SHIPVOICE_APP_PORT"] = str(port)
    log_path = ROOT / "results" / "runtime" / "fastapi_smoke_app.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "run_app.py", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        health = wait_until_ready(base_url, process=process, log_path=log_path)
        base_url = str(health.pop("_base_url", base_url))
        password = os.environ.get("SHIPVOICE_ADMIN_PASSWORD", "shipvoice-admin")
        login_res = post_json(f"{base_url}/api/admin/auth/login", {"password": password})
        token = login_res.get("token")

        overview = get_json(f"{base_url}/api/admin/overview", token=token)
        datasets = get_json(f"{base_url}/api/admin/evaluations", token=token)
        config = get_json(f"{base_url}/api/admin/config", token=token)
        created = post_json(
            f"{base_url}/api/admin/knowledge",
            {
                "title": "FastAPI Smoke Test",
                "tags": ["smoke", "fastapi"],
                "text": "用于自动化验证后端接口。",
            },
            token=token
        )
        record_id = created["record"]["id"]
        detail = get_json(f"{base_url}/api/admin/knowledge/{record_id}", token=token)
        deleted = delete_json(f"{base_url}/api/admin/knowledge/{record_id}", token=token)
        ws_result = {"types": [], "gate": "skipped", "total_ms": None} if args.skip_live_run else websocket_smoke(port)
        payload = {
            "health_ok": health["ok"],
            "service": health["service"],
            "overview_ok": overview["ok"],
            "dataset_count": len(datasets["datasets"]),
            "config_path": config["config_path"],
            "created_id": record_id,
            "detail_title": detail["record"]["title"],
            "deleted_id": deleted["deleted"]["id"],
            "live_run_skipped": args.skip_live_run,
            "ws_types": ws_result["types"],
            "ws_gate": ws_result["gate"],
            "ws_total_ms": ws_result["total_ms"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log_handle.close()


if __name__ == "__main__":
    main()
