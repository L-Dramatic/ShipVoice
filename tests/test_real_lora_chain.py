from __future__ import annotations

import unittest

from scripts.build_acceptance_report import current_lora_chain_status
from scripts.check_real_service_chain import openai_health_url


class RealLoraChainTests(unittest.TestCase):
    def test_health_url_from_openai_base(self) -> None:
        self.assertEqual(openai_health_url("http://127.0.0.1:11434/v1"), "http://127.0.0.1:11434/health")
        self.assertEqual(
            openai_health_url("http://127.0.0.1:11434/v1/chat/completions"),
            "http://127.0.0.1:11434/health",
        )

    def test_lora_chain_requires_served_shipvoice_model_and_adapter(self) -> None:
        verified, _reason = current_lora_chain_status(
            {
                "llm_require_lora": True,
                "llm_health": {
                    "models": ["shipvoice-qwen2.5-7b-lora"],
                    "health": {"adapter_loaded": True},
                },
                "pipeline_result": {
                    "provider_status": {
                        "llm": "openai_compatible:shipvoice-qwen2.5-7b-lora",
                    }
                },
            }
        )
        self.assertTrue(verified)

    def test_base_model_chain_is_not_final_lora_evidence(self) -> None:
        verified, reason = current_lora_chain_status(
            {
                "llm_health": {"models": ["Qwen/Qwen2.5-7B-Instruct"]},
                "pipeline_result": {
                    "provider_status": {
                        "llm": "openai_compatible:Qwen/Qwen2.5-7B-Instruct",
                    }
                },
            }
        )
        self.assertFalse(verified)
        self.assertIn("ShipVoice LoRA", reason)


if __name__ == "__main__":
    unittest.main()
