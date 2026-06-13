from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.config import load_config  # noqa: E402
from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402


class EvidenceCitationTests(unittest.TestCase):
    def test_pipeline_returns_structured_citations(self) -> None:
        config = load_config()
        pipeline = VoiceQAPipeline(config)
        result = asyncio.run(pipeline.run_once("密闭舱室动火作业前要检查什么？", mode="full"))

        self.assertGreaterEqual(len(result.evidence), 1)
        top_hit = result.evidence[0]
        self.assertEqual(top_hit.record_id, "KS001")
        self.assertEqual(top_hit.risk_level, "critical")
        self.assertGreater(top_hit.confidence, 0)
        self.assertIn("密闭舱室", top_hit.matched_terms)
        self.assertIn("ship_safety_corpus.jsonl", top_hit.source)
        self.assertIn("[KS001]", result.answer)


if __name__ == "__main__":
    unittest.main()
