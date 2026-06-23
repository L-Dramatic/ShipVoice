# ShipVoice Repeated Real Chain Experiment

- Generated at: 2026-06-22T18:18:14.814718+00:00
- Repeats: 5
- Modes: baseline, streaming
- Selected samples: 30
- Total ok runs: 300 / 300
- Gate-allowed matched pairs: 100

## Gate-Allowed Latency

| Metric | Baseline avg | Baseline p50 | Streaming avg | Streaming p50 | Streaming p90 | Streaming p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| First audio ready ms | 7967.04 | 7373.5 | 3819.65 | 3869.0 | 5110.7 | 5371.3 |
| LLM first delta ms | 0.0 | 0.0 | 219.29 | 213.0 | 223.0 | 230.45 |
| Streamed audio segments | 0.0 | 0.0 | 3.87 | 3.0 | 6.0 | 6.05 |

## First Audio Saved

- Gate-allowed average saved: 4147.39 ms.
- Gate-allowed p50/p90/p95 saved: 3416.0 / 7659.0 / 8693.25 ms.
- Gate-allowed faster count: 100 / 100.
