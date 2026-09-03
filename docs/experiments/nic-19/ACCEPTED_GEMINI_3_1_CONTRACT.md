# NIC-19 accepted Gemini 3.1 Flash-Lite contract

This prospective contract is an explicitly approved substitution for the
unusable Gemini 2.5 Flash-Lite contract documented in
`GEMINI_2_5_INVESTIGATION.md`. It applies only to new accepted runs. The
historical incomplete Gemini 3.1 trial artifacts in `run-1.json`,
`run-2.json`, and `RESULTS.md` remain unchanged and are not accepted evidence.

- Provider: Google Gemini Developer API, direct HTTPS, `v1beta`.
- Model: `gemini-3.1-flash-lite`.
- Interpreter: `gemini-condition-state-shadow` version `3.0.0`.
- Prompt version: `nic-19-gemini-3.1-flash-lite-accepted-v1`.
- Endpoint form: `models/gemini-3.1-flash-lite:generateContent`.
- Prompt and structured schema: exact frozen constants in
  `backend/tests/condition_state_eval/gemini_adapter.py`.
- Generation configuration: temperature `0.0`, top-p `1.0`, maximum output
  tokens `256`, JSON response MIME type, and the frozen JSON response schema.
- Corpus fingerprint (SHA-256 of `dataset.py`):
  `a33660f69461ea77c9025927f736a4055584464afd4643c61ce7da282ec2e147`.
- Rules baseline interpreter fingerprint (SHA-256):
  `827e23a3677e831ccddb02d0b5e7d40742575e3e7aeac01a87db0698baaeb905`.

The frozen operational protocol is `nic-19-fixed-rate-limit-v1`: one serialized
request at a time; an eight-second inter-request delay; a 30-second request
timeout; only HTTP 429 retryable; at most four attempts per case; the provider
`Retry-After` delay when supplied, otherwise a fixed 60-second delay. Retries
never change the prompt, corpus, expected labels, schema, or generation
configuration. Every attempt is recorded. Any remaining transport or provider
error is an operational error, not semantic `unknown`, and makes a run
incomplete. A run is accepted only when all 41 scored and all 3 diagnostic
cases obtain valid semantic responses.
