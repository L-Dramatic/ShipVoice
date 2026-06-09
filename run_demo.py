from __future__ import annotations

import asyncio
import functools
import json
import socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web" / "static"
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402


def find_free_port(preferred: int = 8010) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free local port found from 8010 to 8029")


def main() -> None:
    port = find_free_port()
    pipeline = VoiceQAPipeline()
    handler = functools.partial(ShipVoiceHandler, directory=str(WEB_ROOT), pipeline=pipeline)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"ShipVoice demo: http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


class ShipVoiceHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, pipeline: VoiceQAPipeline, **kwargs) -> None:
        self.pipeline = pipeline
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self._send_json({"ok": True, "service": "shipvoice"})
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path != "/api/run":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            question = str(payload.get("question", "")).strip()
            mode = str(payload.get("mode", "full")).strip() or "full"
            if not question:
                self._send_json({"error": "missing question"}, status=400)
                return
            result = asyncio.run(self.pipeline.run_once(question, mode=mode))
            self._send_json(
                {
                    "question": result.question,
                    "transcript": result.transcript,
                    "answer": result.answer,
                    "gate": result.gate.__dict__,
                    "evidence": [hit.__dict__ for hit in result.evidence],
                    "events": [event.to_dict() for event in result.events],
                    "metrics": result.metrics.to_row(),
                }
            )
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    main()
