# NIC-19 accepted Gemini 2.5 Flash-Lite contract

This is the accepted pre-corpus contract for the replacement Model-v1 run.
It is distinct from, and does not modify, the historical incomplete Gemini
3.1 trial artifacts in `run-1.json`, `run-2.json`, and `RESULTS.md`.

- Provider: Google Gemini Developer API, direct HTTPS, `v1beta`.
- Model: `gemini-2.5-flash-lite`.
- Interpreter: `gemini-condition-state-shadow` version `2.0.0`.
- Prompt version: `nic-19-gemini-2.5-flash-lite-accepted-v1`.
- Endpoint form: `models/gemini-2.5-flash-lite:generateContent`.
- Prompt and structured schema: the exact frozen constants in
  `backend/tests/condition_state_eval/gemini_adapter.py`.
- Generation configuration: temperature `0.0`, top-p `1.0`, maximum output
  tokens `256`, and JSON response MIME type with the frozen response schema.
- Corpus fingerprint (SHA-256 of `dataset.py`):
  `a33660f69461ea77c9025927f736a4055584464afd4643c61ce7da282ec2e147`.
- Rules baseline interpreter fingerprint (SHA-256):
  `827e23a3677e831ccddb02d0b5e7d40742575e3e7aeac01a87db0698baaeb905`.

The fixed operational protocol is `nic-19-fixed-rate-limit-v1`: serialized
requests; an eight-second inter-request delay; only HTTP 429 is retryable;
at most four attempts for a case; and a provider `Retry-After` delay when
present, otherwise a fixed 60-second delay. Every attempt is retained in the
raw result. A run is accepted only when all 41 scored and all 3 diagnostic
cases have a semantic response; provider failures remain operational errors
and make the run incomplete.
