from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TextIteratorStreamer


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float = 0.2
    top_p: float = 0.9
    max_tokens: int = 512
    stream: bool = False


def _dtype(name: str) -> torch.dtype:
    if name == "float16":
        return torch.float16
    if name == "bfloat16":
        return torch.bfloat16
    if name == "float32":
        return torch.float32
    if torch.cuda.is_available():
        return torch.bfloat16
    return torch.float32


def build_prompt(messages: list[ChatMessage], tokenizer: Any) -> str:
    payload = [{"role": item.role, "content": item.content} for item in messages if item.content.strip()]
    if not payload:
        raise HTTPException(status_code=400, detail="messages is required")
    if hasattr(tokenizer, "apply_chat_template"):
        return tokenizer.apply_chat_template(payload, tokenize=False, add_generation_prompt=True)

    role_blocks = []
    for item in payload:
        role_blocks.append(f"<|im_start|>{item['role']}\n{item['content']}<|im_end|>")
    return "\n".join(role_blocks) + "\n<|im_start|>assistant\n"


def model_input_device(model: torch.nn.Module) -> torch.device:
    try:
        return next(model.parameters()).device
    except StopIteration:
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def hash_directory(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        relative = item.relative_to(path).as_posix()
        stat = item.stat()
        file_count += 1
        total_bytes += stat.st_size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return {
        "adapter_hash_algorithm": "sha256-tree-v1",
        "adapter_sha256": digest.hexdigest() if file_count else "",
        "adapter_file_count": file_count,
        "adapter_bytes": total_bytes,
    }


def create_app(
    *,
    model_path: str,
    served_model_name: str,
    adapter_path: str,
    require_adapter: bool,
    max_new_tokens: int,
    dtype_name: str,
    device: str,
    load_in_4bit: bool,
) -> FastAPI:
    if require_adapter and not adapter_path:
        raise RuntimeError("--require-adapter was set but --adapter-path is empty.")

    adapter_dir = Path(adapter_path).expanduser() if adapter_path else None
    if adapter_dir and not adapter_dir.exists():
        raise FileNotFoundError(f"LoRA adapter path does not exist: {adapter_dir}")
    if require_adapter and adapter_dir and not (adapter_dir / "adapter_config.json").exists():
        raise FileNotFoundError(f"LoRA adapter_config.json not found under: {adapter_dir}")
    adapter_attestation = hash_directory(adapter_dir) if adapter_dir else {
        "adapter_hash_algorithm": "sha256-tree-v1",
        "adapter_sha256": "",
        "adapter_file_count": 0,
        "adapter_bytes": 0,
    }

    torch_dtype = _dtype(dtype_name)
    tokenizer_source = str(adapter_dir) if adapter_dir and (adapter_dir / "tokenizer_config.json").exists() else model_path
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_source, trust_remote_code=True)
    if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
        tokenizer.pad_token = tokenizer.eos_token

    quantization_config = None
    if load_in_4bit:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch_dtype,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )

    load_kwargs: dict[str, Any] = {
        "torch_dtype": torch_dtype,
        "trust_remote_code": True,
        "quantization_config": quantization_config,
    }
    if device == "auto":
        load_kwargs["device_map"] = "auto" if torch.cuda.is_available() else None
    model = AutoModelForCausalLM.from_pretrained(model_path, **load_kwargs)

    if device != "auto":
        model.to(device)
    elif not torch.cuda.is_available():
        model.to("cpu")

    loaded_adapter = ""
    if adapter_dir:
        try:
            from peft import PeftModel
        except ModuleNotFoundError as exc:
            raise RuntimeError("PEFT is required for loading ShipVoice LoRA adapter.") from exc
        model = PeftModel.from_pretrained(model, str(adapter_dir))
        loaded_adapter = str(adapter_dir.resolve())

    model.eval()
    loaded_at = int(time.time())
    input_device = str(model_input_device(model))
    quantization = "4bit" if load_in_4bit else "none"

    app = FastAPI(title="ShipVoice Transformers OpenAI-Compatible LLM")

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "ok": True,
            "service": "transformers_openai",
            "served_model": served_model_name,
            "base_model": model_path,
            "adapter_loaded": bool(loaded_adapter),
            "adapter_path": loaded_adapter,
            "require_adapter": require_adapter,
            **adapter_attestation,
            "device": input_device,
            "dtype": str(torch_dtype).replace("torch.", ""),
            "quantization": quantization,
            "loaded_at": loaded_at,
        }

    @app.get("/v1/models")
    def list_models() -> dict[str, object]:
        return {
            "object": "list",
            "data": [
                {
                    "id": served_model_name,
                    "object": "model",
                    "created": loaded_at,
                    "owned_by": "shipvoice",
                }
            ],
        }

    @app.post("/v1/chat/completions")
    def chat_completions(payload: ChatCompletionRequest):
        if payload.model and payload.model != served_model_name:
            raise HTTPException(
                status_code=404,
                detail=f"requested model {payload.model!r} is not served here; use {served_model_name!r}",
            )

        prompt = build_prompt(payload.messages, tokenizer)
        inputs = tokenizer(prompt, return_tensors="pt")
        input_device_obj = model_input_device(model)
        inputs = {key: value.to(input_device_obj) for key, value in inputs.items()}
        generation_kwargs: dict[str, Any] = {
            "max_new_tokens": min(max(payload.max_tokens, 32), max_new_tokens),
            "eos_token_id": tokenizer.eos_token_id,
            "pad_token_id": tokenizer.eos_token_id,
        }
        if payload.temperature > 0:
            generation_kwargs.update(
                {
                    "do_sample": True,
                    "temperature": max(payload.temperature, 1e-5),
                    "top_p": min(max(payload.top_p, 0.05), 1.0),
                }
            )
        else:
            generation_kwargs["do_sample"] = False

        if payload.stream:
            request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            created = int(time.time())
            streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
            stream_kwargs = {**generation_kwargs, "streamer": streamer}
            errors: list[BaseException] = []

            def run_generation() -> None:
                try:
                    with torch.no_grad():
                        model.generate(**inputs, **stream_kwargs)
                except BaseException as exc:
                    errors.append(exc)
                    if hasattr(streamer, "on_finalized_text"):
                        streamer.on_finalized_text("", stream_end=True)

            def sse_events():
                for text in streamer:
                    if not text:
                        continue
                    chunk = {
                        "id": request_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": served_model_name,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": text},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                if errors:
                    error_chunk = {
                        "id": request_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": served_model_name,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": "error",
                            }
                        ],
                        "error": str(errors[0]),
                    }
                    yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
                else:
                    final_chunk = {
                        "id": request_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": served_model_name,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            threading.Thread(target=run_generation, daemon=True).start()
            return StreamingResponse(sse_events(), media_type="text/event-stream")

        with torch.no_grad():
            generated = model.generate(**inputs, **generation_kwargs)

        prompt_tokens = int(inputs["input_ids"].shape[-1])
        completion_tokens = int(generated.shape[-1] - prompt_tokens)
        output_ids = generated[0][prompt_tokens:]
        content = tokenizer.decode(output_ids, skip_special_tokens=True).strip()
        if not content:
            raise HTTPException(status_code=502, detail="model returned an empty answer")

        now = int(time.time())
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": now,
            "model": served_model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": int(generated.shape[-1]),
            },
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a local Hugging Face model with OpenAI-compatible chat endpoints.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--model-path", default="")
    parser.add_argument("--served-model-name", default="")
    parser.add_argument("--adapter", default="")
    parser.add_argument("--adapter-path", default="")
    parser.add_argument("--require-adapter", action="store_true")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--dtype", choices=["auto", "float16", "bfloat16", "float32"], default="auto")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--load-in-4bit", action="store_true")
    args = parser.parse_args()

    model_path = args.model_path or args.model
    adapter_path = args.adapter_path or args.adapter
    served_model_name = args.served_model_name or ("shipvoice-qwen2.5-7b-lora" if adapter_path else model_path)

    import uvicorn

    app = create_app(
        model_path=model_path,
        served_model_name=served_model_name,
        adapter_path=adapter_path,
        require_adapter=args.require_adapter,
        max_new_tokens=args.max_new_tokens,
        dtype_name=args.dtype,
        device=args.device,
        load_in_4bit=args.load_in_4bit,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
