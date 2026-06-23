"""Build the final ShipVoice course report PDF from the curated Markdown file."""

from __future__ import annotations

import re
from pathlib import Path

import markdown
from weasyprint import CSS, HTML


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "deliverables" / "final_submission" / "report"
REPORT_MD = REPORT_DIR / "ShipVoice_船厂安全实时语音问答助手_项目报告_最终版.md"
REPORT_PDF = REPORT_MD.with_suffix(".pdf")

CSS_TEXT = """
@page { size: A4; margin: 2cm 2.2cm; }
body {
  font-family: "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif;
  font-size: 11pt;
  line-height: 1.55;
  color: #111;
}
h1 { color: #2E74B5; font-size: 18pt; page-break-before: always; margin-top: 0; }
h1:first-of-type { page-break-before: avoid; }
h2 { color: #2E74B5; font-size: 15pt; margin-top: 16pt; }
h3 { color: #1F4D78; font-size: 13pt; margin-top: 12pt; }
h4 { color: #1F4D78; font-size: 12pt; margin-top: 10pt; }
p { text-align: justify; margin: 6pt 0; }
table {
  border-collapse: collapse;
  width: auto;
  max-width: 100%;
  margin: 8pt 0 12pt;
  font-size: 9pt;
  table-layout: auto;
  text-align: left;
}
th, td {
  border: 1px solid #C8D0DC;
  padding: 3pt 5pt;
  vertical-align: top;
  text-align: left !important;
  white-space: normal;
  word-wrap: break-word;
  overflow-wrap: break-word;
  hyphens: auto;
}
th { background: #F4F6F9; font-weight: 700; }
img { max-width: 100%; height: auto; display: block; margin: 8pt auto 4pt; }
pre, code { font-family: Menlo, Consolas, monospace; font-size: 8.8pt; }
pre {
  background: #F2F4F7;
  padding: 8pt;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid #E2E6ED;
}
em { color: #555; font-size: 10pt; }
ul, ol { margin: 6pt 0 10pt 18pt; }
"""


def normalize_table_separators(content: str) -> str:
    """Remove markdown column alignment markers so cells stay left-aligned."""

    def fix_line(line: str) -> str:
        if re.match(r"^\|[-: |]+\|$", line):
            return re.sub(r":", "-", line)
        return line

    return "\n".join(fix_line(line) for line in content.split("\n"))


def strip_table_cell_alignment(html: str) -> str:
    """Strip inline text-align from table cells (markdown tables extension adds these)."""

    def clean_tag(match: re.Match[str]) -> str:
        tag, attrs = match.group(1), match.group(2)
        attrs = re.sub(
            r'\s*style="[^"]*text-align:\s*[^;"]+;?\s*[^"]*"',
            "",
            attrs,
        )
        attrs = re.sub(r'\s*align="(left|right|center)"', "", attrs)
        return f"<{tag}{attrs}>"

    return re.sub(r"<(th|td)([^>]*)>", clean_tag, html)


def rewrite_image_paths(content: str) -> str:
    def repl(match: re.Match[str]) -> str:
        alt, path = match.group(1), match.group(2)
        resolved = (REPORT_DIR / path).resolve()
        if not resolved.exists():
            return f"**[图片缺失: {alt}]**"
        return f"![{alt}]({resolved.as_uri()})"

    return re.sub(r"!\[(.*?)\]\((.*?)\)", repl, content)


def replace_mermaid_blocks(content: str) -> str:
    assets_dir = REPORT_DIR / "assets" / "diagrams"
    pattern = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)

    def repl(match: re.Match[str]) -> str:
        for name in ("system_architecture.png", "system_architecture.svg"):
            image_path = assets_dir / name
            if image_path.exists():
                rel = Path("..") / "assets" / "diagrams" / name
                return f"![系统架构图]({rel.as_posix()})\n\n*图 3-1 ShipVoice 系统架构数据流*"
        return match.group(0)

    return pattern.sub(repl, content)


def build_pdf() -> Path:
    markdown_text = REPORT_MD.read_text(encoding="utf-8")
    markdown_text = replace_mermaid_blocks(markdown_text)
    markdown_text = normalize_table_separators(markdown_text)
    markdown_text = rewrite_image_paths(markdown_text)
    html_body = markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    html_body = strip_table_cell_alignment(html_body)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>ShipVoice 项目报告</title></head>
<body>{html_body}</body>
</html>"""
    REPORT_PDF.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=str(REPORT_DIR.resolve())).write_pdf(
        str(REPORT_PDF),
        stylesheets=[CSS(string=CSS_TEXT)],
    )
    return REPORT_PDF


def main() -> None:
    pdf_path = build_pdf()
    print(pdf_path)


if __name__ == "__main__":
    main()
