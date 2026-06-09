from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INCLUDE_DIRS = ["configs", "data", "docs", "remote", "scripts", "src", "web"]
INCLUDE_FILES = ["README.md", "requirements.txt", "run_demo.py"]
EXCLUDE_PARTS = {"__pycache__", ".git"}
EXCLUDE_SUFFIXES = {".pyc", ".tmp", ".log"}


def should_include(path: Path) -> bool:
    if any(part in EXCLUDE_PARTS for part in path.parts):
        return False
    if path.suffix in EXCLUDE_SUFFIXES:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an AutoDL upload bundle.")
    parser.add_argument("--out", default=str(ROOT / "results" / "autodl_bundle.zip"))
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirname in INCLUDE_DIRS:
            base = ROOT / dirname
            if not base.exists():
                continue
            for file in base.rglob("*"):
                if file.is_file() and should_include(file.relative_to(ROOT)):
                    zf.write(file, file.relative_to(ROOT).as_posix())
        for filename in INCLUDE_FILES:
            file = ROOT / filename
            if file.exists():
                zf.write(file, file.relative_to(ROOT).as_posix())

    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

