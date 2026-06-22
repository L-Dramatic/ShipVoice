from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.config import project_path  # noqa: E402
from shipvoice.models import RetrievalHit  # noqa: E402
from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402
from shipvoice.providers import HybridRetriever  # noqa: E402


class EvidenceCitationTests(unittest.TestCase):
    def test_retriever_returns_structured_citations(self) -> None:
        import asyncio

        retriever = HybridRetriever(project_path("data", "knowledge", "ship_safety_index.json"))
        evidence = asyncio.run(retriever.retrieve("密闭舱室动火作业前要检查什么？"))

        self.assertGreaterEqual(len(evidence), 1)
        top_hit = evidence[0]
        self.assertEqual(top_hit.record_id, "KS001")
        self.assertEqual(top_hit.risk_level, "critical")
        self.assertGreater(top_hit.confidence, 0)
        self.assertIn("密闭舱室", top_hit.matched_terms)
        self.assertIn("ship_safety_corpus.jsonl", top_hit.source)

    def test_pipeline_attaches_auditable_citation_id_to_answer(self) -> None:
        evidence = [
            RetrievalHit(
                record_id="KS001",
                title="密闭舱室与有限空间作业",
                text="进入前完成通风和气体检测。",
                score=10,
                source="ship_safety_corpus.jsonl",
                risk_level="critical",
                matched_terms=["密闭舱室"],
                confidence=1.0,
            )
        ]

        answer = VoiceQAPipeline._attach_answer_citations("进入前先完成审批、通风和检测。", evidence)

        self.assertIn("[KS001]", answer)
        self.assertIn("密闭舱室与有限空间作业", answer)


if __name__ == "__main__":
    unittest.main()
