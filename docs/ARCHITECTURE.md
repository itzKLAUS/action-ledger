# Architecture

Django serves both the dashboard and JSON API. Browser sessions use password hashing, CSRF tokens and tenant membership. Service credentials are 256-bit random tokens; only their SHA-256 digest is persisted. Service keys can submit, inspect, lease and complete their own actions, but cannot review or change policies. A deployment operator provisions users and keys through management commands.

Each mutating service starts a PostgreSQL transaction and locks the workspace row before reading policy/budget state. All domain writes and audit append operations share that lock. This intentionally serializes mutations within one workspace; unrelated workspaces can proceed independently. SQLite is supported only for sequential local development and production rejects it.

## State machine

`pending → approved → leased → succeeded/failed`

Alternative exits: `pending → rejected/cancelled`, `approved → cancelled`, and a denied request is terminal. Failed executions consume their reserved bound because their external cost may be uncertain. Completion retries with the same token/result are idempotent; conflicting results fail. No lease expiry or automatic replay is implemented.

A new policy revision deactivates its predecessors. An approval under an inactive policy cannot obtain a new lease. Existing leases remain issued authority; this is an explicit boundary, not retroactive revocation. Pending reservations may be cancelled by the requester or an owner. Already leased requests require service-side reconciliation.

The ledger binds operation, destination, declared cost and canonical argument digest. Raw arguments remain in the trusted execution service. An opaque digest neither validates the argument semantics nor prevents a compromised tool client from bypassing the ledger. Callbacks must enforce their own network and cost boundaries, and external credentials must be scoped independently.

## Audit evidence

The chain hashes previous digest, sequence, event kind, actor and payload. The workspace stores the head and count. Verification locks the workspace to obtain a stable snapshot. Timestamps are informational and are not included in the chain. Exported heads need independent anchoring for resistance to privileged rewriting; such anchoring is a future extension, not an implemented guarantee.

## Intentional limits

- Integer cents are a declared accounting unit, not a payment transaction or live provider billing integration.
- Role provisioning is a trusted CLI operation; there is no invitation email, SSO or built-in MFA.
- No external tool executes inside the web service.
- Budget period rollover and expired-pending-request cleanup are not automatic.
- The dashboard shows the latest 100 actions and 500 audit events; full JSON audit export is available to members. Very large exports need a streaming/pagination extension.
- No background workers or paid third-party services are required.
