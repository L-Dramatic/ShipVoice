from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parents[1]


async def run(args: argparse.Namespace) -> dict[str, Any]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=args.browser,
            headless=args.headless,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
                "--disable-features=AudioServiceOutOfProcess",
            ],
        )
        page = await browser.new_page()
        await page.goto(args.html.resolve().as_uri(), wait_until="load", timeout=30000)
        await page.click("#startButton", timeout=10000)
        await page.wait_for_function(
            "() => window.__shipvoiceBrowserBatchResult && window.__shipvoiceBrowserBatchResult.done === true",
            timeout=args.timeout_ms,
        )
        result = await page.evaluate("() => window.__shipvoiceBrowserBatchResult")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.screenshot:
            await page.screenshot(path=str(args.screenshot), full_page=True)
        await browser.close()
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the generated browser onplaying batch harness with Chromium.")
    parser.add_argument("--html", type=Path, default=ROOT / "results" / "browser_onplaying_batch_20260623.html")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "browser_onplaying_batch_20260623.json")
    parser.add_argument("--screenshot", type=Path, default=ROOT / "results" / "browser_onplaying_batch_20260623.png")
    parser.add_argument("--browser", default=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    parser.add_argument("--timeout-ms", type=int, default=900000)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    args.headless = not args.headed
    result = asyncio.run(run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
