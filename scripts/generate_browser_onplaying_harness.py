from __future__ import annotations

import argparse
import base64
import csv
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def select_rows(rows: list[dict[str, str]], *, split: str, limit: int, sample_ids: set[str]) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in rows:
        if sample_ids and row.get("id", "") not in sample_ids:
            continue
        if split and row.get("split", "") != split:
            continue
        audio_path = ROOT / row.get("audio_path", "")
        if not audio_path.exists():
            continue
        selected.append(row)
        if limit and len(selected) >= limit:
            break
    return selected


def build_samples(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    for row in rows:
        audio_path = ROOT / row["audio_path"]
        samples.append(
            {
                "id": row.get("id", ""),
                "audio_name": audio_path.name,
                "transcript": row.get("transcript", ""),
                "scenario": row.get("scenario", ""),
                "audio_base64": base64.b64encode(audio_path.read_bytes()).decode("ascii"),
            }
        )
    return samples


def render_html(samples: list[dict[str, str]], *, ws_url: str, output_json_name: str) -> str:
    samples_json = json.dumps(samples, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>ShipVoice Browser Onplaying Batch</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; line-height: 1.45; }}
    button {{ padding: 8px 14px; }}
    pre {{ white-space: pre-wrap; background: #f6f8fa; padding: 12px; border: 1px solid #d0d7de; }}
    .row {{ margin: 8px 0; }}
  </style>
</head>
<body>
  <h1>ShipVoice Browser Onplaying Batch</h1>
  <p>Samples: <span id="sampleCount"></span></p>
  <button id="startButton">Start Browser Batch</button>
  <div id="status"></div>
  <pre id="results">{{}}</pre>
  <script>
    const SAMPLES = {samples_json};
    const WS_URL = {json.dumps(ws_url)};
    const OUTPUT_JSON_NAME = {json.dumps(output_json_name)};
    const resultsEl = document.getElementById("results");
    const statusEl = document.getElementById("status");
    document.getElementById("sampleCount").textContent = String(SAMPLES.length);

    function nowMs(startedAt) {{
      return Math.max(0, Math.round(performance.now() - startedAt));
    }}

    function base64ToBlob(base64, mimeType) {{
      const binary = atob(base64);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) {{
        bytes[index] = binary.charCodeAt(index);
      }}
      return new Blob([bytes], {{ type: mimeType || "audio/mpeg" }});
    }}

    function pct(values, p) {{
      const nums = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
      if (!nums.length) return 0;
      if (nums.length === 1) return Math.round(nums[0] * 100) / 100;
      const pos = (nums.length - 1) * p;
      const lower = Math.floor(pos);
      const upper = Math.min(lower + 1, nums.length - 1);
      const weight = pos - lower;
      return Math.round((nums[lower] * (1 - weight) + nums[upper] * weight) * 100) / 100;
    }}

    function stat(values) {{
      const nums = values.filter((value) => Number.isFinite(value));
      return {{
        count: nums.length,
        avg: nums.length ? Math.round((nums.reduce((a, b) => a + b, 0) / nums.length) * 100) / 100 : 0,
        p50: pct(nums, 0.5),
        p90: pct(nums, 0.9),
        p95: pct(nums, 0.95),
        min: nums.length ? Math.min(...nums) : 0,
        max: nums.length ? Math.max(...nums) : 0
      }};
    }}

    function playFirstChunk(chunk, startedAt) {{
      return new Promise((resolve) => {{
        let settled = false;
        const audio = new Audio();
        audio.muted = true;
        audio.preload = "auto";
        const blob = base64ToBlob(chunk.audio_base64, chunk.mime_type || "audio/mpeg");
        const url = URL.createObjectURL(blob);
        const finish = (payload) => {{
          if (settled) return;
          settled = true;
          audio.pause();
          URL.revokeObjectURL(url);
          resolve(payload);
        }};
        audio.onplaying = () => finish({{
          ok: true,
          client_audio_onplaying_ms: nowMs(startedAt),
          audio_base64_len: chunk.audio_base64.length,
          mime_type: chunk.mime_type || "audio/mpeg"
        }});
        audio.onerror = () => finish({{
          ok: false,
          error: "audio error",
          client_audio_onplaying_ms: null,
          audio_base64_len: chunk.audio_base64.length,
          mime_type: chunk.mime_type || "audio/mpeg"
        }});
        audio.src = url;
        const promise = audio.play();
        if (promise && typeof promise.catch === "function") {{
          promise.catch((error) => finish({{
            ok: false,
            error: error && error.message ? error.message : "play rejected",
            client_audio_onplaying_ms: null,
            audio_base64_len: chunk.audio_base64.length,
            mime_type: chunk.mime_type || "audio/mpeg"
          }}));
        }}
        setTimeout(() => finish({{
          ok: false,
          error: "onplaying timeout",
          client_audio_onplaying_ms: null,
          audio_base64_len: chunk.audio_base64.length,
          mime_type: chunk.mime_type || "audio/mpeg"
        }}), 15000);
      }});
    }}

    async function runSample(sample, index) {{
      const startedAt = performance.now();
      const requestId = `browser_onplaying_${{Date.now()}}_${{sample.id}}_${{index}}`;
      const row = {{
        sample_id: sample.id,
        audio_name: sample.audio_name,
        transcript_reference: sample.transcript,
        request_id: requestId,
        status: "running",
        audio_chunks: 0,
        first_audio_chunk_arrival_ms: null,
        client_audio_onplaying_ms: null,
        result_arrival_ms: null,
        play_error: "",
        server_first_audio_chunk_ready_ms: null,
        llm_first_delta_ms: null,
        streamed_audio_segments: null,
        response_mode: ""
      }};
      let firstChunkPlay = null;
      let resultSeen = false;
      return await new Promise((resolve) => {{
        const socket = new WebSocket(WS_URL);
        const settle = () => {{
          if (resultSeen && (row.client_audio_onplaying_ms !== null || row.play_error || row.audio_chunks === 0)) {{
            row.status = row.play_error ? "play_error" : "ok";
            resolve(row);
          }}
        }};
        const timeout = setTimeout(() => {{
          row.status = "timeout";
          try {{ socket.close(); }} catch (error) {{}}
          resolve(row);
        }}, 180000);
        socket.onopen = () => {{
          socket.send(JSON.stringify({{
            session_id: "browser-onplaying-batch",
            client_request_id: requestId,
            mode: "streaming",
            audio_base64: sample.audio_base64,
            audio_name: sample.audio_name,
            question: ""
          }}));
        }};
        socket.onmessage = async (event) => {{
          const payload = JSON.parse(event.data);
          if (payload.type === "audio_chunk") {{
            const chunk = payload.chunk || {{}};
            row.audio_chunks += 1;
            if (row.first_audio_chunk_arrival_ms === null) {{
              row.first_audio_chunk_arrival_ms = nowMs(startedAt);
              row.server_first_audio_chunk_ready_ms = chunk.server_first_audio_chunk_ready_ms ?? chunk.server_audio_chunk_ready_ms ?? null;
              firstChunkPlay = playFirstChunk(chunk, startedAt).then((play) => {{
                if (play.ok) {{
                  row.client_audio_onplaying_ms = play.client_audio_onplaying_ms;
                }} else {{
                  row.play_error = play.error || "play failed";
                }}
                settle();
              }});
            }}
          }} else if (payload.type === "result") {{
            row.result_arrival_ms = nowMs(startedAt);
            resultSeen = true;
            const result = payload.result || {{}};
            const metrics = result.metrics || {{}};
            const providers = result.provider_status || result.providers || {{}};
            row.llm_first_delta_ms = metrics.llm_first_delta_ms ?? null;
            row.streamed_audio_segments = metrics.streamed_audio_segments ?? null;
            row.response_mode = providers.response_mode || "";
            clearTimeout(timeout);
            if (!firstChunkPlay && result.audio_output && Array.isArray(result.audio_output.audio_segments) && result.audio_output.audio_segments.length) {{
              row.audio_chunks = result.audio_output.audio_segments.length;
              row.first_audio_chunk_arrival_ms = row.result_arrival_ms;
              firstChunkPlay = playFirstChunk({{
                audio_base64: result.audio_output.audio_segments[0],
                mime_type: result.audio_output.mime_type || "audio/mpeg"
              }}, startedAt).then((play) => {{
                if (play.ok) {{
                  row.client_audio_onplaying_ms = play.client_audio_onplaying_ms;
                }} else {{
                  row.play_error = play.error || "play failed";
                }}
                settle();
              }});
            }}
            try {{ socket.close(); }} catch (error) {{}}
            settle();
          }} else if (payload.type === "error") {{
            row.status = "error";
            row.error = payload.error || "websocket error";
            clearTimeout(timeout);
            try {{ socket.close(); }} catch (error) {{}}
            resolve(row);
          }}
        }};
        socket.onerror = () => {{
          row.status = "socket_error";
          clearTimeout(timeout);
          resolve(row);
        }};
        socket.onclose = () => {{
          if (!resultSeen && row.status === "running") {{
            row.status = "closed_before_result";
            clearTimeout(timeout);
            resolve(row);
          }}
        }};
      }});
    }}

    async function runBatch() {{
      const rows = [];
      for (let index = 0; index < SAMPLES.length; index += 1) {{
        const sample = SAMPLES[index];
        statusEl.innerHTML = `<div class="row">Running ${{index + 1}} / ${{SAMPLES.length}}: ${{sample.id}}</div>`;
        rows.push(await runSample(sample, index + 1));
        resultsEl.textContent = JSON.stringify({{ done: false, rows }}, null, 2);
      }}
      const okRows = rows.filter((row) => row.status === "ok" && Number.isFinite(row.client_audio_onplaying_ms));
      const summary = {{
        done: true,
        output_json_name: OUTPUT_JSON_NAME,
        generated_at: new Date().toISOString(),
        ws_url: WS_URL,
        num_samples: rows.length,
        num_ok: okRows.length,
        num_failed: rows.length - okRows.length,
        client_audio_onplaying_ms: stat(okRows.map((row) => row.client_audio_onplaying_ms)),
        first_audio_chunk_arrival_ms: stat(okRows.map((row) => row.first_audio_chunk_arrival_ms)),
        server_first_audio_chunk_ready_ms: stat(okRows.map((row) => row.server_first_audio_chunk_ready_ms)),
        result_arrival_ms: stat(okRows.map((row) => row.result_arrival_ms)),
        llm_first_delta_ms: stat(okRows.map((row) => row.llm_first_delta_ms)),
        rows
      }};
      window.__shipvoiceBrowserBatchResult = summary;
      resultsEl.textContent = JSON.stringify(summary, null, 2);
      statusEl.innerHTML = `<div class="row">Done: ${{okRows.length}} / ${{rows.length}}</div>`;
    }}

    document.getElementById("startButton").addEventListener("click", () => {{
      document.getElementById("startButton").disabled = true;
      runBatch().catch((error) => {{
        const payload = {{ done: true, fatal_error: error && error.message ? error.message : String(error) }};
        window.__shipvoiceBrowserBatchResult = payload;
        resultsEl.textContent = JSON.stringify(payload, null, 2);
      }});
    }});
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a browser page for real onplaying latency batch capture.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "audio" / "audio_manifest.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "browser_onplaying_batch_20260623.html")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8026/ws/run")
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--sample-ids", default="")
    parser.add_argument("--output-json-name", default="browser_onplaying_batch_20260623.json")
    args = parser.parse_args()

    selected = select_rows(
        read_manifest(args.manifest),
        split=args.split,
        limit=args.limit,
        sample_ids={item.strip() for item in args.sample_ids.split(",") if item.strip()},
    )
    if not selected:
        raise SystemExit("no runnable audio rows selected")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_html(build_samples(selected), ws_url=args.ws_url, output_json_name=args.output_json_name),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "samples": len(selected)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
