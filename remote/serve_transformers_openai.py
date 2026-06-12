from __future__ import annotations

import argparse
import time
import uuid

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import AutoModelForCausalLM, AutoTokenizer


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float = 0.2
    max_tokens: int = 512
    stream: bool = False


def build_prompt(messages: list[ChatMessage], tokenizer) -> str:
    payload = [{"role": item.role, "content": item.content} for item in messages if item.content.strip()]
    if not payload:
        raise HTTPException(status_code=400, detail="messages is required")
    return tokenizer.apply_chat_template(payload, tokenize=False, add_generation_prompt=True)


def create_app(model_name: str, max_new_tokens: int) -> FastAPI:
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.float16,
        trust_remote_code=True,
    )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()

    app = FastAPI(title="ShipVoice Transformers OpenAI-Compatible LLM")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true", "service": "transformers_openai", "model": model_name}

    @app.get("/v1/models")
    def list_models() -> dict[str, object]:
        now = int(time.time())
        return {
            "object": "list",
            "data": [
                {
                    "id": model_name,
                    "object": "model",
                    "created": now,
                    "owned_by": "shipvoice",
                }
            ],
        }

    @app.post("/v1/chat/completions")
    def chat_completions(payload: ChatCompletionRequest) -> dict[str, object]:
        if payload.stream:
            raise HTTPException(status_code=400, detail="stream=true is not supported")
        prompt = build_prompt(payload.messages, tokenizer)
        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        generated = model.generate(
            **inputs,
            max_new_tokens=min(max(payload.max_tokens, 32), max_new_tokens),
            do_sample=payload.temperature > 0,
            temperature=max(payload.temperature, 1e-5),
            top_p=0.9,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.eos_token_id,
        )
        completion_tokens = generated.shape[-1] - inputs["input_ids"].shape[-1]
        output_ids = generated[0][inputs["input_ids"].shape[-1] :]
        content = tokenizer.decode(output_ids, skip_special_tokens=True).strip()
        now = int(time.time())
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": now,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": int(inputs["input_ids"].shape[-1]),
                "completion_tokens": int(completion_tokens),
                "total_tokens": int(generated.shape[-1]),
            },
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a local Hugging Face model with OpenAI-compatible chat endpoints.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    args = parser.parse_args()

    import uvicorn

    app = create_app(args.model, args.max_new_tokens)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
