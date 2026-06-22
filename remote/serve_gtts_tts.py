from __future__ import annotations

import argparse
import base64
import re
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from gtts import gTTS
from pydantic import BaseModel
from pydub import AudioSegment


class TTSRequest(BaseModel):
    text: str
    voice: str = "zh-CN"


def split_text(text: str, max_chars: int = 80) -> list[str]:
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
    return re.sub(r"\s+", " ", normalized).strip()


def build_app(default_lang: str) -> FastAPI:
    app = FastAPI(title="ShipVoice gTTS Service")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true", "service": "gtts", "lang": default_lang}

    @app.post("/tts")
    def tts(payload: TTSRequest) -> dict[str, str]:
        text = normalize_text(payload.text.strip())
        if not text:
            raise HTTPException(status_code=400, detail="text is required")

        lang = (payload.voice or default_lang).strip() or default_lang
        text_chunks = split_text(text)
        temp_paths: list[Path] = []

        try:
            combined = AudioSegment.silent(duration=0)
            for chunk in text_chunks:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp:
                    temp_path = Path(temp.name)
                temp_paths.append(temp_path)
                gTTS(text=chunk, lang=lang).save(str(temp_path))
                combined += AudioSegment.from_file(temp_path, format="mp3")

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as merged:
                merged_path = Path(merged.name)
            temp_paths.append(merged_path)
            combined.export(merged_path, format="mp3")
            audio_base64 = base64.b64encode(merged_path.read_bytes()).decode("ascii")
            return {
                "audio_base64": audio_base64,
                "mime_type": "audio/mpeg",
                "provider": f"gtts:{lang}",
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
    parser = argparse.ArgumentParser(description="Serve gTTS over HTTP.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--lang", default="zh-CN")
    args = parser.parse_args()

    app = build_app(args.lang)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
