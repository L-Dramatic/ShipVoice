# ShipVoice Server Real Streaming Comparison

- Generated at: 2026-06-22T17:25:37.612146+00:00
- Baseline samples: 30 ok / 0 failed
- Streaming samples: 30 ok / 0 failed
- Gate-allowed matched samples: 20

## Gate-Allowed Latency

| Metric | Baseline avg | Streaming avg | Streaming p50 | Streaming p90 | Streaming p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| First audio ready ms | 7161.9 | 3834.9 | 3655.5 | 5285.9 | 5389.6 |
| LLM first delta ms | 0.0 | 209.45 | 211.5 | 217.1 | 218.1 |
| Streamed audio segments | 0.0 | 4.4 | 4.0 | 6.1 | 7.0 |

## First Audio Saved

- All ok samples avg saved: 2244.57 ms; p50 1822.0 ms.
- Gate-allowed samples avg saved: 3327.0 ms; p50 2820.5 ms.
- Gate-allowed faster count: 20 / 20.
