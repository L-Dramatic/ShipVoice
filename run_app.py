from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.config import load_env_file  # noqa: E402
from shipvoice.fastapi_app import create_app  # noqa: E402


def find_free_port(preferred: int = 8022) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free local port found from {preferred} to {preferred + 19}")


def ensure_port_available(host: str, port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise RuntimeError(f"Port {host}:{port} is not available.") from exc
    return port


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the ShipVoice FastAPI app.")
    parser.add_argument("--env-file", default=os.getenv("SHIPVOICE_ENV_FILE", ""), help="Optional .env-style runtime file.")
    parser.add_argument("--port", type=int, default=0, help="Preferred local port. Overrides SHIPVOICE_APP_PORT.")
    parser.add_argument("--host", default=os.getenv("SHIPVOICE_APP_HOST", "127.0.0.1"), help="Bind host.")
    parser.add_argument("--no-auto-port", action="store_true", help="Fail if the requested port is occupied.")
    args = parser.parse_args()

    if args.env_file:
        loaded = load_env_file(args.env_file)
        print(f"Loaded env file: {loaded['SHIPVOICE_ENV_FILE']}")

    preferred_port = args.port or int(os.getenv("SHIPVOICE_APP_PORT", "8022"))
    no_auto_port = args.no_auto_port or os.getenv("SHIPVOICE_NO_AUTO_PORT", "").strip().lower() in {"1", "true", "yes", "on"}
    port = ensure_port_available(args.host, preferred_port) if no_auto_port else find_free_port(preferred_port)
    app = create_app()
    print(f"Runtime profile: ASR={os.getenv('SHIPVOICE_ASR_PROVIDER', '(config)')} "
          f"LLM={os.getenv('SHIPVOICE_LLM_PROVIDER', '(config)')} "
          f"TTS={os.getenv('SHIPVOICE_TTS_PROVIDER', '(config)')}")
    if os.getenv("SHIPVOICE_ASR_ENDPOINT"):
        print(f"ASR endpoint: {os.getenv('SHIPVOICE_ASR_ENDPOINT')}")
    if os.getenv("SHIPVOICE_OPENAI_BASE_URL"):
        print(f"LLM base URL: {os.getenv('SHIPVOICE_OPENAI_BASE_URL')}")
    if os.getenv("SHIPVOICE_TTS_ENDPOINT"):
        print(f"TTS endpoint: {os.getenv('SHIPVOICE_TTS_ENDPOINT')}")
    print(f"ShipVoice FastAPI: http://{args.host}:{port}")
    print(f"ShipVoice Admin:   http://{args.host}:{port}/admin.html")
    print(f"OpenAPI docs:      http://{args.host}:{port}/docs")
    uvicorn.run(app, host=args.host, port=port, log_level="info")


if __name__ == "__main__":
    main()
