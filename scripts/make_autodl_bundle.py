from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INCLUDE_DIRS = ["configs", "data", "docs", "remote", "scripts", "src", "web"]
INCLUDE_FILES = ["README.md", "requirements.txt", "run_app.py"]
INCLUDE_RESULT_FILES = [
    "remote_lora_expanded_summary_20260621.json",
    "remote_autodl_20260621_expanded/summary.json",
]
EXCLUDE_PARTS = {"__pycache__", ".git"}
EXCLUDE_SUFFIXES = {".pyc", ".tmp", ".log"}
LORA_ADAPTER_SOURCE = (
    ROOT
    / "results"
    / "remote_autodl_20260621_expanded"
    / "extracted"
    / "outputs"
    / "qwen_lora_shipvoice_expanded"
)
LORA_ADAPTER_DEST = Path("outputs") / "qwen_lora_shipvoice_expanded"
REQUIRED_LORA_FILES = {"adapter_config.json", "adapter_model.safetensors"}


def should_include(path: Path) -> bool:
    if any(part in EXCLUDE_PARTS for part in path.parts):
        return False
    if path.suffix in EXCLUDE_SUFFIXES:
        return False
    return True


def add_tree(zf: zipfile.ZipFile, source: Path, dest: Path) -> int:
    count = 0
    for file in source.rglob("*"):
        if file.is_file() and should_include(file.relative_to(ROOT)):
            arcname = dest / file.relative_to(source)
            zf.write(file, arcname.as_posix())
            count += 1
    return count


def verify_lora_adapter(source: Path) -> None:
    if not source.exists():
        raise SystemExit(f"ShipVoice LoRA adapter directory not found: {source}")
    missing = sorted(name for name in REQUIRED_LORA_FILES if not (source / name).exists())
    if missing:
        raise SystemExit(f"ShipVoice LoRA adapter is incomplete under {source}; missing: {', '.join(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an AutoDL upload bundle.")
    parser.add_argument("--out", default=str(ROOT / "results" / "autodl_bundle.zip"))
    parser.add_argument("--allow-missing-lora-adapter", action="store_true")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    adapter_files = 0
    if not args.allow_missing_lora_adapter:
        verify_lora_adapter(LORA_ADAPTER_SOURCE)

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirname in INCLUDE_DIRS:
            base = ROOT / dirname
            if not base.exists():
                continue
            add_tree(zf, base, Path(dirname))
        for filename in INCLUDE_FILES:
            file = ROOT / filename
            if file.exists():
                zf.write(file, file.relative_to(ROOT).as_posix())
        for filename in INCLUDE_RESULT_FILES:
            file = ROOT / "results" / filename
            if file.exists():
                zf.write(file, (Path("results") / filename).as_posix())
        if LORA_ADAPTER_SOURCE.exists():
            adapter_files = add_tree(zf, LORA_ADAPTER_SOURCE, LORA_ADAPTER_DEST)

    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
    print(f"included ShipVoice LoRA adapter files: {adapter_files}")


if __name__ == "__main__":
    main()
