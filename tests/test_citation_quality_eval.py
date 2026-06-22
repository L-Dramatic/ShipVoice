from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_citation_quality import citation_complete, summarize  # noqa: E402
from shipvoice.models import RetrievalHit  # noqa: E402


class CitationQualityEvalTests(unittest.TestCase):
    def test_citation_complete_requires_auditable_fields(self) -> None:
        complete = RetrievalHit(
            record_id="KS001",
            title="密闭舱室与有限空间作业",
            text="进入前完成通风和气体检测。",
            score=10,
            source="ship_safety_corpus.jsonl",
            risk_level="critical",
            matched_terms=["密闭舱室"],
            confidence=1.0,
        )
        missing_terms = RetrievalHit(
            record_id="KS002",
            title="舾装阶段管路试压",
            text="试压前确认隔离和泄漏风险。",
            score=8,
            source="ship_safety_corpus.jsonl",
            risk_level="high",
            matched_terms=[],
            confidence=0.8,
        )

        self.assertTrue(citation_complete(complete))
        self.assertFalse(citation_complete(missing_terms))

    def test_summarize_reports_hit_and_schema_rates(self) -> None:
        rows = [
            {
                "expected_allowed": True,
                "gate_allowed_match": True,
                "expected_title": "密闭舱室与有限空间作业",
                "expected_record_id": "KS001",
                "citation_count": 3,
                "complete_citation_count": 2,
                "title_hit_at_1": True,
                "title_hit_at_3": True,
                "id_hit_at_1": True,
                "id_hit_at_3": True,
                "top1_complete": True,
                "answer_has_citation_id": True,
                "top1_confidence": 1.0,
                "total_ms": 2400,
                "mode": "full",
            },
            {
                "expected_allowed": False,
                "gate_allowed_match": True,
                "expected_title": "",
                "expected_record_id": "",
                "citation_count": 0,
                "complete_citation_count": 0,
                "title_hit_at_1": False,
                "title_hit_at_3": False,
                "id_hit_at_1": False,
                "id_hit_at_3": False,
                "top1_complete": False,
                "answer_has_citation_id": False,
                "top1_confidence": "",
                "total_ms": 1800,
                "mode": "full",
            },
        ]

        summary = summarize(rows)

        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["allowed_cases"], 1)
        self.assertEqual(summary["blocked_cases"], 1)
        self.assertEqual(summary["gate_allowed_accuracy"], 1.0)
        self.assertEqual(summary["citation_title_hit_at_3"], 1.0)
        self.assertEqual(summary["top1_schema_completeness"], 1.0)
        self.assertEqual(summary["citation_schema_completeness"], 2 / 3)
        self.assertEqual(summary["answer_citation_id_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
