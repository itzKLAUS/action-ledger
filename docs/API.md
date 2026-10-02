# API and OpenAI integration

Issue a key with `python manage.py service_key WORKSPACE_ID LABEL`. The secret is shown once; store it securely, not in source control or browser storage. Revoke with `service_key WORKSPACE_ID LABEL --revoke KEY_ID`. Commands require trusted deployment access.

All `/api/v1/` endpoints require `Authorization: Bearer <service-key>`. Cookies are never accepted as API authority. Mutations use `application/json`. Browser mutations use sessions plus CSRF.

## Submit

`POST /api/v1/actions/`

```json
{"operation":"invoice.send","destination":"billing.example.com","cost_cents":100,"arguments_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","idempotency_key":"invoice-001"}
```

Returns 201 for a new action, 200 for an identical replay, 400 for validation/idempotency conflicts, 401 without an active key. Response includes `id`, `status`, `reason`, operation/destination/cost and argument digest. Keys are scoped to their workspace and action requester. Policy-denied decisions are recorded objects, not transport errors.

## Inspect, lease and complete

- `GET /api/v1/actions/UUID/`: inspect your action; unrelated action IDs return 404.
- `POST /api/v1/actions/UUID/lease/`: obtain `{ "lease_token": "..." }` once, after approval and while its policy remains active. Store the token durably before the external operation. A lost lease response leaves the intent leased; reconcile it, never assume execution did not happen.
- `POST /api/v1/actions/UUID/complete/`: `{ "lease_token": "...", "success": true, "result_digest": "<SHA-256>" }`. Failed execution also consumes the declared bound. Identical completion retries succeed; conflicts return 400. Invalid lease tokens return 403.

Django handles permissions with 403 and missing objects with 404. Error bodies for these may be HTML; clients must check the HTTP status rather than assuming every response is JSON. Application validation errors have a JSON `error` string. No credentials, raw arguments or raw results belong in logs.

## Python client

`sdk.LedgerClient` uses the standard library and disables HTTP redirects to keep credentials at the configured origin. TLS is mandatory except for explicitly enabled localhost development. `execute` resumes an intent with its stable idempotency key and calls your trusted callback only after a matching approved decision, successful lease and durable checkpoint. Supply the required `persist_lease(action, token, arguments)` callable to commit the lease and argument snapshot to your application’s protected durable store. A checkpoint failure stops execution and leaves the lease parked for reconciliation. Never log the token.

`DecisionPending.action_id` is a durable checkpoint, not successful tool output. Persist the call arguments, model call ID and action ID securely in your application. Resume the same idempotency key after reviewer approval. If a completion request fails after a callback ran, reconcile using the saved lease token; do not call the tool again. The supplied client is a small integration reference, not a durable distributed execution engine.

## OpenAI Responses

`examples_openai.py` contains a strict function-tool schema and `dispatch(call, ledger, persist_lease)` for a Responses `function_call` item. It makes no model calls and uses a synthetic preview callback. Configure an `invoice.preview` policy for `billing.example.com` before using it. Connect it to your server's Responses loop; only actual completed/denied calls become `function_call_output` items. A pending decision is returned as an application checkpoint for human review.

If you add live model calls, install the OpenAI SDK separately, keep `OPENAI_API_KEY` on the server, and explicitly authorize the API cost. The example does not claim to bypass or replace the Agents SDK approval machinery.
