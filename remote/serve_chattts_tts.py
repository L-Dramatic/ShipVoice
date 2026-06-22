from __future__ import annotations

import argparse
import base64
import os
import re
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class TTSRequest(BaseModel):
    text: str
    voice: str = ""


def normalize_text(text: str) -> str:
    normalized = text
    replacements = {
        "《": "",
        "》": "",
        "“": "",
        "”": "",
        "\n": " ",
        "\r": " ",
        "\t": " ",
    }
    for src, dst in replacements.items():
        normalized = normalized.replace(src, dst)
    return re.sub(r"\s+", " ", normalized).strip()


def build_chat():
    import ChatTTS

    source = os.environ.get("CHATTTS_SOURCE", "huggingface")
    custom_path = os.environ.get("CHATTTS_CUSTOM_PATH")
    chat = ChatTTS.Chat()
    if hasattr(chat, "load"):
        chat.load(source=source, custom_path=custom_path, compile=False)
    else:
        chat.load_models(compile=False)
    return chat


def build_app() -> FastAPI:
    chat = build_chat()
    app = FastAPI(title="ShipVoice ChatTTS Service")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true", "service": "chattts", "sample_rate": "24000"}

    @app.post("/tts")
    def tts(payload: TTSRequest) -> dict[str, str]:
        text = normalize_text(payload.text.strip())
        if not text:
            raise HTTPException(status_code=400, detail="text is required")

        try:
            wavs = chat.infer([text])
            if not wavs:
                raise RuntimeError("empty waveform result")

            import numpy as np
            import soundfile as sf

            wav = wavs[0]
            if isinstance(wav, list):
                wav = np.asarray(wav, dtype=np.float32)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
                temp_path = Path(temp.name)
            try:
                sf.write(str(temp_path), wav, 24000)
                audio_base64 = base64.b64encode(temp_path.read_bytes()).decode("ascii")
            finally:
                temp_path.unlink(missing_ok=True)

            return {
                "audio_base64": audio_base64,
                "mime_type": "audio/wav",
                "provider": "chattts",
            }
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"tts failed: {exc}") from exc

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve ChatTTS over HTTP.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()

    app = build_app()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
