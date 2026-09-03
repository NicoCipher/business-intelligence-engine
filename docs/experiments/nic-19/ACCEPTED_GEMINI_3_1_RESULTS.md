# NIC-19 accepted Gemini 3.1 Flash-Lite results

These are the accepted results for the prospective contract in
`ACCEPTED_GEMINI_3_1_CONTRACT.md`. They are separate from the historical,
incomplete exploratory Gemini 3.1 artifacts (`run-1.json`, `run-2.json`, and
`RESULTS.md`), which remain unchanged.

## Completeness and reproducibility

Both runs used the same committed provider, model, prompt, JSON schema,
generation configuration, timeout, and `nic-19-fixed-rate-limit-v1` protocol.
Each has all 41 scored cases and all 3 diagnostics exactly once, with valid
semantic responses, zero operational failures, and zero retries.

| Artifact | SHA-256 | Scored / diagnostic | Complete |
| --- | --- | --- | --- |
| `accepted-gemini-3.1-run-1.json` | `d6249ec4cf6d0c242d57eec336684ce899d80fb44f3a86b4814e595c30ffc38d` | 41 / 3 | yes |
| `accepted-gemini-3.1-run-2.json` | `7332e30d58a928036fcb43490af8ddd11adb6a1a55fff174a67aed51b5972334` | 41 / 3 | yes |

The runs have identical labels, literal evidence spans, and raw structured
outputs for all 44 cases. Run 1 used 11,481 input and 2,353 output tokens
(13,834 total); run 2 reported the same totals. The API did not return billed
cost metadata, so cost is recorded as unavailable rather than estimated.

## Independently recomputed scored metrics

The raw records were independently checked for corpus coverage, uniqueness,
expected-label correspondence, literal evidence-span grounding, and agreement
between raw JSON and stored fields. Re-scoring from the raw records reproduced
the stored metrics for both runs exactly:

| Metric | Run 1 | Run 2 |
| --- | ---: | ---: |
| Correct / 41 | 31 | 31 |
| Accuracy | 0.756 | 0.756 |
| Wrong | 10 | 10 |
| Critically wrong | 0 | 0 |
| Semantic unknown rate | 0.341 | 0.341 |
| Null abstentions | 0 | 0 |
| Operational failures | 0 | 0 |

Per-label precision / recall is active 0.579 / 1.000, resolved 0.750 / 1.000,
and unknown 1.000 / 0.583. All ten errors are expected-unknown cases predicted
as active or resolved. Diagnostics remain separate and unscored.

## Frozen rules-v1 comparison

The rules interpreter remains byte-identical (blob
`3d3ed36eb8bcf5ec7398f1f28490ae375573b46c`; SHA-256
`827e23a3677e831ccddb02d0b5e7d40742575e3e7aeac01a87db0698baaeb905`). Its
standalone frozen evaluation reproduced exactly with output SHA-256
`db74f39fc68d173de6b6a8e9c90f4c559efd47e83c0b008e9d9264d3e6369404`:
7/41 accuracy (0.171), one critical inversion, seven wrong, nine null
abstentions, 17 correct abstentions, and no operational errors.

On this frozen corpus, Gemini has higher scored accuracy (31/41 versus 7/41)
and no critical inversions, but it never abstains and misses ten expected
unknown cases. This is bounded shadow-evaluation evidence, not a production
readiness claim. The real-world holdout remains unavailable / not reproducibly
materialized.

## Leakage and tuning controls

The model invocation accepts only `InterpreterCase(case_id, source_text,
target_span)`, which excludes `expected_label`; scoring happens after the
response is recorded. The prompt, corpus, schema, model, generation settings,
and quota protocol were committed before the accepted corpus requests. No
semantic change was made between runs or after examining outcomes.
