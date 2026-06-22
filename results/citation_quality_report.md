# ShipVoice Citation Quality Evaluation

This report evaluates whether generated answers are grounded in auditable RAG citations, not just whether retrieval returns any text.

- Samples: 8
- Allowed citation cases: 5
- Blocked cases: 3
- Gate allowed accuracy: 100.00%
- Citation title hit@1: 100.00%
- Citation title hit@3: 100.00%
- Citation ID hit@1: 100.00%
- Citation ID hit@3: 100.00%
- Top-1 schema completeness: 100.00%
- Citation schema completeness: 100.00%
- Answer citation ID rate: 100.00%
- Avg top-1 confidence: 1.000
- Avg total latency: 5309 ms

| ID | Category | Gate | Expected citation | Top-1 citation | Hit@3 | Complete | Answer cites ID |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Q001 | safety | domain_safe | KS001 | KS001 | Yes | Yes | Yes |
| Q002 | term | domain_safe | KS002 | KS002 | Yes | Yes | Yes |
| Q003 | lifting | domain_safe | KS003 | KS003 | Yes | Yes | Yes |
| Q004 | welding | domain_safe | KS004 | KS004 | Yes | Yes | Yes |
| Q005 | off_domain | off_domain | blocked | none | n/a | n/a | n/a |
| Q006 | unsafe | unsafe | blocked | none | n/a | n/a | n/a |
| Q007 | prompt_injection | unsafe | blocked | none | n/a | n/a | n/a |
| Q008 | term | domain_safe | KS005 | KS005 | Yes | Yes | Yes |
