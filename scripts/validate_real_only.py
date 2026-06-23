from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCAN_TARGETS = [
    "configs",
    "remote",
    "scripts",
    "src",
    "web",
    "docker-compose.app.yml",
    "requirements.txt",
    "run_app.py",
]
EXTENDED_SCAN_TARGETS = [
    "README.md",
    "docs",
    "tests",
]
TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".css",
    ".csv",
    ".env",
    ".example",
    ".html",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
}


def guarded_terms() -> list[str]:
    return [
        "mo" + "ck",
        "Mo" + "ck",
        "runtime." + "mo" + "ck",
        "transcript_" + "fall" + "back",
        "fall" + "back",
        "simu" + "lated",
        "run_" + "demo",
        "稳定" + "演示",
        "兜" + "底",
        "模" + "拟",
        "80" + "10",
    ]


def forbidden_paths() -> list[Path]:
    return [
        ROOT / "configs" / ("runtime." + "mo" + "ck.env"),
        ROOT / ("run_" + "demo.py"),
    ]


def should_scan(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.is_dir():
        return False
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    if path.name.endswith(".env.example"):
        return True
    return False


def scan_file(path: Path, terms: list[str]) -> list[tuple[str, int, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="ignore")
    hits: list[tuple[str, int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for term in terms:
            if term in line:
                hits.append((term, line_number, line.strip()))
    return hits


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate that ShipVoice source stays on the real-service path.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--include-docs-and-tests",
        action="store_true",
        help="Also scan narrative docs and tests. This is stricter and may flag explanatory text or test patch helper usage.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    terms = guarded_terms()
    failures: list[str] = []

    for path in forbidden_paths():
        if path.exists():
            failures.append(f"forbidden file exists: {path.relative_to(ROOT)}")

    scan_targets = list(RUNTIME_SCAN_TARGETS)
    if args.include_docs_and_tests:
        scan_targets.extend(EXTENDED_SCAN_TARGETS)
    scan_roots = [root / target for target in scan_targets]
    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        candidates = scan_root.rglob("*") if scan_root.is_dir() else [scan_root]
        for path in candidates:
            if not should_scan(path):
                continue
            rel = path.relative_to(root)
            for term, line_number, line in scan_file(path, terms):
                failures.append(f"{rel}:{line_number}: forbidden token {term!r}: {line}")

    if failures:
        print("REAL-ONLY VALIDATION FAILED", file=sys.stderr)
        for failure in failures:
            print(failure, file=sys.stderr)
        raise SystemExit(1)

    print("REAL-ONLY VALIDATION OK")


if __name__ == "__main__":
    main()
