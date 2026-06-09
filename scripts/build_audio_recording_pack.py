from __future__ import annotations

import csv
import html
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "audio" / "audio_manifest.csv"
OUT = ROOT / "deliverables" / "ShipVoice_Audio_Recording_Pack.html"


def read_manifest() -> list[dict[str, str]]:
    with MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def metric(label: str, value: str, note: str = "") -> str:
    return f"""
    <article class="metric">
      <span>{html.escape(label)}</span>
      <strong>{html.escape(value)}</strong>
      <em>{html.escape(note)}</em>
    </article>
    """


def build() -> None:
    rows = read_manifest()
    by_noise = Counter(row["noise_condition"] for row in rows)
    by_scenario = Counter(row["scenario"] for row in rows)
    missing = sum(1 for row in rows if row["status"] == "missing")

    task_rows = [
        [
            row["id"],
            row["scenario"],
            row["noise_condition"],
            row["audio_path"],
            row["transcript"],
        ]
        for row in rows
    ]
    scenario_rows = [[name, str(count)] for name, count in sorted(by_scenario.items())]
    noise_rows = [[name, str(count)] for name, count in sorted(by_noise.items())]

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ShipVoice Audio Recording Pack</title>
  <style>
    :root {{
      --ink: #101827;
      --muted: #667085;
      --bg: #f5f7fb;
      --line: #d9e2ec;
      --navy: #0b2545;
      --blue: #2563eb;
      --green: #10b981;
      --gold: #f59e0b;
      --red: #dc2626;
      --surface: #fff;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif; }}
    header {{ background: var(--navy); color: white; padding: 42px 56px 34px; }}
    header h1 {{ margin: 0; font-size: 40px; letter-spacing: 0; }}
    header p {{ margin: 12px 0 0; color: #b9d6ff; font-size: 18px; }}
    main {{ padding: 28px 56px 56px; display: grid; gap: 24px; }}
    section {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 22px; box-shadow: 0 16px 40px rgba(16, 24, 40, .06); }}
    h2 {{ margin: 0 0 14px; font-size: 24px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 14px; }}
    .metric {{ border: 1px solid var(--line); border-left: 5px solid var(--blue); border-radius: 8px; padding: 16px; background: #fbfdff; min-height: 112px; }}
    .metric span {{ display:block; color: var(--muted); font-size: 13px; }}
    .metric strong {{ display:block; margin-top: 10px; font-size: 30px; }}
    .metric em {{ display:block; margin-top: 8px; color: var(--muted); font-style: normal; font-size: 13px; line-height: 1.4; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: top; }}
    th {{ background: #f2f4f7; font-weight: 700; }}
    .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    .steps {{ counter-reset: step; display: grid; gap: 12px; }}
    .step {{ border-left: 5px solid var(--green); background: #f6fef9; padding: 14px 16px; line-height: 1.7; }}
    .step strong {{ display: block; margin-bottom: 4px; }}
    code {{ background: #eef2f7; padding: 2px 5px; border-radius: 4px; }}
    @media (max-width: 900px) {{ main, header {{ padding-left: 22px; padding-right: 22px; }} .metrics, .grid2 {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>ShipVoice Audio Recording Pack</h1>
    <p>Real speech collection plan for ASR and voice-QA evaluation.</p>
  </header>
  <main>
    <section>
      <h2>Recording Target</h2>
      <div class="metrics">
        {metric("Recording tasks", str(len(rows)), "manifest rows")}
        {metric("Missing audio", str(missing), "to be recorded")}
        {metric("Noise conditions", str(len(by_noise)), "quiet / classroom / workshop-like")}
        {metric("Scenarios", str(len(by_scenario)), "safe, unsafe, off-domain, injection")}
      </div>
    </section>

    <section>
      <h2>How To Record</h2>
      <div class="steps">
        <div class="step"><strong>1. Use the exact transcript.</strong> Do not paraphrase. ASR evaluation needs a stable reference text.</div>
        <div class="step"><strong>2. Save each file with the listed path/name.</strong> Example: <code>data/audio/raw/A001.wav</code>.</div>
        <div class="step"><strong>3. Recommended format.</strong> WAV, mono, 16 kHz or 24 kHz. Keep each clip around 3-8 seconds.</div>
        <div class="step"><strong>4. Fill speaker and status.</strong> Update <code>speaker</code> and change <code>status</code> from <code>missing</code> to <code>recorded</code>.</div>
        <div class="step"><strong>5. After ASR.</strong> Fill <code>asr_transcript</code> and <code>asr_provider</code>, then run <code>python scripts/evaluate_asr_transcripts.py</code>.</div>
      </div>
    </section>

    <section>
      <h2>Coverage</h2>
      <div class="grid2">
        <div>{table(["Noise condition", "Count"], noise_rows)}</div>
        <div>{table(["Scenario", "Count"], scenario_rows)}</div>
      </div>
    </section>

    <section>
      <h2>Recording Tasks</h2>
      {table(["ID", "Scenario", "Noise", "Output path", "Read exactly this transcript"], task_rows)}
    </section>
  </main>
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_text, encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    build()
