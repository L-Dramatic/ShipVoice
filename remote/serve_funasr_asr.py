from __future__ import annotations

import argparse
import base64
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess


class ASRRequest(BaseModel):
    audio_base64: str
    audio_name: str = "input.wav"
    transcript_hint: str = ""


def build_app(
    *,
    model_name: str,
    device: str,
    language: str,
    batch_size_s: int,
    merge_length_s: int,
) -> FastAPI:
    model = AutoModel(
        model=model_name,
        vad_model="fsmn-vad",
        vad_kwargs={"max_single_segment_time": 30000},
        device=device,
    )

    app = FastAPI(title="ShipVoice FunASR Service")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true", "service": "funasr_asr", "model": model_name, "device": device}

    @app.post("/asr")
    def asr(payload: ASRRequest) -> dict[str, str]:
        if not payload.audio_base64.strip():
            raise HTTPException(status_code=400, detail="audio_base64 is required")

        try:
            audio_bytes = base64.b64decode(payload.audio_base64)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid base64 audio: {exc}") from exc

        suffix = Path(payload.audio_name or "input.wav").suffix or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
            temp.write(audio_bytes)
            temp_path = temp.name

        try:
            result = model.generate(
                input=temp_path,
                cache={},
                language=language,
                use_itn=True,
                batch_size_s=batch_size_s,
                merge_vad=True,
                merge_length_s=merge_length_s,
            )
            raw_text = ""
            if result and isinstance(result, list):
                raw_text = str(result[0].get("text", ""))
            text = rich_transcription_postprocess(raw_text).strip()
            if not text and payload.transcript_hint.strip():
                text = payload.transcript_hint.strip()
            return {
                "text": text,
                "provider": "funasr_sensevoice_service",
                "audio_name": payload.audio_name,
            }
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"asr failed: {exc}") from exc
        finally:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve FunASR/SenseVoice ASR over HTTP.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--model", default="iic/SenseVoiceSmall")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--batch-size-s", type=int, default=60)
    parser.add_argument("--merge-length-s", type=int, default=15)
    args = parser.parse_args()

    app = build_app(
        model_name=args.model,
        device=args.device,
        language=args.language,
        batch_size_s=args.batch_size_s,
        merge_length_s=args.merge_length_s,
    )

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
