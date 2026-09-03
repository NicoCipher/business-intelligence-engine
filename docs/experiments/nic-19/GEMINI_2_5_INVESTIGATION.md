# NIC-19 Gemini 2.5 Flash-Lite availability investigation

The original Model-v1 contract named `gemini-2.5-flash-lite`. Before an
accepted corpus run, authenticated model metadata was queried through the
Google Gemini Developer API `v1beta` endpoint. It returned HTTP 200 for that
exact identifier and advertised `generateContent` among its supported methods.
The matching entry also appeared in the authenticated model list.

A synthetic, non-corpus structured-output request was then sent using direct
HTTPS to the documented endpoint form
`models/gemini-2.5-flash-lite:generateContent`, the same `v1beta` API version,
and the frozen NIC-19 request shape. It reproducibly returned HTTP 404. No
NIC-17 case was sent to the model. The request took 540.16 ms and returned no
usage telemetry.

The source request path and identifier matched the documented API contract.
The metadata and generation responses were nevertheless inconsistent for the
actual BIA key/API path. The retained evidence does not expose the provider's
full error detail, so it does not establish a precise provider-side cause.
The supported conclusion is only that `gemini-2.5-flash-lite` was unusable for
NIC-19 through the actual BIA key/API path at this time. No 2.5 corpus run is
accepted.
