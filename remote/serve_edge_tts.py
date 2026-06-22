from __future__ import annotations

import argparse
import base64
import re
import tempfile
from pathlib import Path

import edge_tts
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class TTSRequest(BaseModel):
    text: str
    voice: str = "zh-CN-XiaoxiaoNeural"


def split_text(text: str, max_chars: int = 120) -> list[str]:
    parts = [chunk.strip() for chunk in re.split(r"(?<=[。！？；!?;])", text) if chunk.strip()]
    if not parts:
        parts = [text.strip()]
    chunks: list[str] = []
    current = ""
    for part in parts:
        if not current:
            current = part
            continue
        if len(current) + len(part) <= max_chars:
            current += part
        else:
            chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks


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
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def build_app(default_voice: str) -> FastAPI:
    app = FastAPI(title="ShipVoice Edge TTS Service")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true", "service": "edge_tts", "voice": default_voice}

    @app.post("/tts")
    async def tts(payload: TTSRequest) -> dict[str, str]:
        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")

        voice = payload.voice.strip() or default_voice
        chunks = split_text(normalize_text(text))
        combined_audio = bytearray()
        temp_paths: list[Path] = []

        try:
            for chunk in chunks:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp:
                    temp_path = Path(temp.name)
                temp_paths.append(temp_path)
                communicator = edge_tts.Communicate(text=chunk, voice=voice)
                await communicator.save(str(temp_path))
                combined_audio.extend(temp_path.read_bytes())
            audio_base64 = base64.b64encode(bytes(combined_audio)).decode("ascii")
            return {
                "audio_base64": audio_base64,
                "mime_type": "audio/mpeg",
                "provider": f"edge_tts:{voice}",
            }
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"tts failed: {exc}") from exc
        finally:
            for temp_path in temp_paths:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Edge TTS over HTTP.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    args = parser.parse_args()

    app = build_app(args.voice)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
