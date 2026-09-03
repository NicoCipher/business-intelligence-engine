# NIC-19 controlled Gemini evaluation

## Frozen experiment and provenance

- Frozen operational configuration commit: `1fc2843f253ae48c8de0836bc5acf9b418bea056`.
- Provider/model: Google Gemini Developer API / `gemini-3.1-flash-lite`.
- The authenticated model list advertised `models/gemini-3.1-flash-lite`, display name `Gemini 3.1 Flash Lite`, version `3.1-flash-lite-05-2026`, with `generateContent` in `supportedGenerationMethods`.
- Prompt version: `nic-19-gemini-2.5-flash-lite-v1` (unchanged).
- Generation configuration: temperature `0.0`, topP `1.0`, maxOutputTokens `256`, response MIME type `application/json`.
- Labels and structured schema are unchanged: `active`, `resolved`, `unknown`, or `null`, with exactly `label`, `evidence_span`, and `rationale` fields.
- Transport remains direct HTTPS to Gemini Developer API `v1beta`; retry policy is none.

The model identifier correction from 2.5 to 3.1 was an operational provider availability correction before this evaluation, not semantic tuning. No prompt, model, parsing, corpus, or rules-baseline change was made after results were observed.

Frozen NIC-18 proof:

| Artifact | SHA256 |
| --- | --- |
| `rules_interpreter.py` | `827e23a3677e831ccddb02d0b5e7d40742575e3e7aeac01a87db0698baaeb905` |
| Reproduced standalone rules-baseline output | `db74f39fc68d173de6b6a8e9c90f4c559efd47e83c0b008e9d9264d3e6369404` |

Complete per-case records, including expected/predicted labels, literal evidence spans, raw structured responses, operational errors, latency, token usage, and execution parameters, are in [run-1.json](run-1.json) and [run-2.json](run-2.json).

## Scored results

Accuracy is calculated over non-operational responses, matching the frozen scorer's separate operational-error axis. Precision/recall likewise exclude operational failures. `unknown` rate is explicit model `unknown`; no model response used `null`, so the effective unknown-or-null rate is the same.

| Metric | RUN 1 | RUN 2 |
| --- | ---: | ---: |
| Scored cases attempted | 41 | 41 |
| Successful scored responses | 21 | 30 |
| Accuracy | 17/21 = 0.810 | 25/30 = 0.833 |
| Correct | 17 | 25 |
| Wrong | 4 | 5 |
| Critically wrong | 0 | 0 |
| Abstained / null | 0 | 0 |
| Correct abstention | 0 | 0 |
| Explicit unknown prediction rate | 7/21 = 0.333 | 12/30 = 0.400 |
| Operational failures | 20 | 11 |

| Label | RUN 1 precision / recall | RUN 2 precision / recall |
| --- | ---: | ---: |
| active | 0.700 / 1.000 | 0.692 / 1.000 |
| resolved | 0.750 / 1.000 | 0.800 / 1.000 |
| unknown | 1.000 / 0.636 | 1.000 / 0.706 |

Every operational failure was `Gemini API HTTP 429: Too Many Requests` and is recorded separately from the semantic label `unknown`.

## Failure classification

The table covers every scored failure in each run. No direct active/resolved inversion occurred.

| Run | Classification | Case IDs |
| --- | --- | --- |
| RUN 1 | Historical-state overclaim: expected `unknown`, predicted `resolved` | `CS-CORE-004` |
| RUN 1 | Conflicting/partial-state overclaim: expected `unknown`, predicted `active` | `CS-CORE-009`, `CS-CORE-010`, `CS-CORE-012` |
| RUN 1 | Provider rate limit (`HTTP 429`), no semantic prediction | `CS-CORE-020`, `CS-CORE-021`, `CS-CORE-023`, `CS-CORE-024`, `CS-CORE-025`, `CS-CORE-026`, `CS-CORE-027`, `CS-CORE-028`, `CS-CORE-N1`, `CS-CORE-N2`, `CS-ADV-001`, `CS-ADV-002`, `CS-ADV-003`, `CS-ADV-006`, `CS-ADV-007`, `CS-ADV-008`, `CS-ADV-009`, `CS-ADV-010`, `CS-ADV-011`, `CS-ADV-012` |
| RUN 2 | Historical-state overclaim: expected `unknown`, predicted `resolved` | `CS-CORE-004` |
| RUN 2 | Conflicting/partial-state overclaim: expected `unknown`, predicted `active` | `CS-CORE-009`, `CS-CORE-010`, `CS-CORE-012` |
| RUN 2 | Lexical-good-state false positive: expected `unknown`, predicted `active` | `CS-CORE-028` |
| RUN 2 | Provider rate limit (`HTTP 429`), no semantic prediction | `CS-CORE-N1`, `CS-CORE-N2`, `CS-ADV-001`, `CS-ADV-002`, `CS-ADV-005`, `CS-ADV-006`, `CS-ADV-007`, `CS-ADV-008`, `CS-ADV-009`, `CS-ADV-010`, `CS-ADV-012` |

## Run-to-run comparison

Among the 20 scored cases that returned a valid response in both runs, labels matched on all 20: exact label agreement `20/20 = 1.000`. There were no label disagreements and no evidence/rationale-only variations among jointly successful responses.

The 11 availability disagreements below are not label disagreements; one run received HTTP 429 while the other received a valid prediction:

- `CS-CORE-020`, `CS-CORE-021`, `CS-CORE-023`, `CS-CORE-024`, `CS-CORE-027`, `CS-ADV-011`: RUN 1 429; RUN 2 `unknown`.
- `CS-CORE-025`, `CS-ADV-003`: RUN 1 429; RUN 2 `active`.
- `CS-CORE-026`: RUN 1 429; RUN 2 `resolved`.
- `CS-CORE-028`: RUN 1 429; RUN 2 `active`.
- `CS-ADV-005`: RUN 1 `unknown`; RUN 2 429.

## Diagnostics (not scored)

The three diagnostic cases were evaluated in their own section after scored cases in each run. All six requests failed operationally with HTTP 429, so no diagnostic semantic observation is claimed.

| Case ID | RUN 1 | RUN 2 |
| --- | --- | --- |
| `CS-CORE-007` | HTTP 429 | HTTP 429 |
| `CS-CORE-008` | HTTP 429 | HTTP 429 |
| `CS-ADV-004` | HTTP 429 | HTTP 429 |

## Latency, token usage, and cost

Latency includes all 44 requests in each run, including rejected requests. Token totals include only responses for which Gemini returned usage metadata.

| Metric | RUN 1 | RUN 2 |
| --- | ---: | ---: |
| Requests | 44 | 44 |
| Latency min / p50 / p95 / max (ms) | 307.56 / 883.54 / 2607.04 / 3378.94 | 481.50 / 1446.18 / 2051.57 / 2663.46 |
| Mean latency (ms) | 1253.88 | 1272.79 |
| Input tokens | 5481 | 7803 |
| Output tokens | 1122 | 1605 |
| Total tokens | 6603 | 9408 |
| Cost | unavailable (`null`) | unavailable (`null`) |

## Direct frozen rules-v1 comparison

The reproduced frozen rules-v1 baseline is 41 scored cases, accuracy `7/41 = 0.171`, `critically_wrong = 1`, `wrong = 7`, `abstained = 9`, `correct_abstention = 17`, `error = 0`, and unknown prediction rate `0.634`.

Gemini's conditional scored-response accuracy is higher in both runs, and it has no critical inversions in returned responses. The comparison is materially limited: Gemini had 20 and 11 provider failures respectively, whereas the local rules baseline had none, so neither Gemini run supplies a complete 41-case score. The recorded `unknown` rates are explicit Gemini `unknown` labels; rules-v1's published rate is based on its abstention representation.

## Verification and limits

- Focused NIC-17/NIC-18/NIC-19 tests: `38 passed`.
- Standalone frozen rules evaluation: executed; output hash above matched.
- Standalone Gemini checks: two independent saved runs above; no retries.
- Full backend suite: `969 passed in 152.18s` using Python 3.11 and a fresh isolated `BIA_DATA_DIR`.
- No corpus case was transmitted outside the two authorized controlled runs; each API payload contained only its corresponding NIC-17 case. No holdout was accessed or constructed.
- holdout unavailable / not reproducibly materialized

The provider's HTTP 429 rate limit means this is a recorded controlled experiment, not a complete reliability benchmark. No repair or tuning follows from these results; independent review is required before any subsequent work.
