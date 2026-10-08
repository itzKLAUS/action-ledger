# Verification â€” 2026-10-01

Local checks were executed in Docker with synthetic data and no production credentials. Test containers had no external network or host credentials. PostgreSQL tests used an internal Docker network with a disposable database; previews and a pinned browser tool used a separate internal network.

- PostgreSQL 17, Python 3.12: **34 tests pass**, no skipped tests. Includes competing budget submissions, idempotent intent/completion, single leases, invalid costs/hosts, own-request review rejection, tenant/service isolation, credential revocation, CSRF, login throttling, provisioning and SDK checkpoint failures.
- Branch-inclusive coverage, excluding tests and migrations: **86%** across core and SDK. This is measured test coverage, not a security guarantee.
- Ruff lint and format checks pass; migration drift check reports no changes; Django system checks report no issues.
- Production image builds as a non-root runtime user with hash-checked dependencies. `check --deploy --fail-level WARNING` reports no issues with production settings and a synthetic long secret.
- Production image smoke check renders login over simulated HTTPS, redirects HTTP and serves hashed CSS successfully.
- Real SDK-to-HTTP smoke workflow: submit â†’ approve via auto-allow policy â†’ lease â†’ checkpoint hook â†’ synthetic callback â†’ completion. Replaying the completed intent executes no callback.
- Browser sign-in succeeds; an owner cannot approve their own pending request; a separate reviewer can approve it and the queue updates.
- Runtime Python dependency audit reports no known vulnerabilities. Container OS scanning and independent review are not complete.

The production image check did not connect to a production database or TLS proxy. PostgreSQL workflow tests separately exercised the data contract. CI is configured for Python 3.12/3.13 and PostgreSQL; This historical record predates the public release. See the latest public-release verification section and the linked GitHub Actions runs for current evidence.

Open deployment requirements: trusted TLS proxy, gateway MFA/SSO, workload-specific load tests, backup/restore exercise, secret rotation, least-privilege database roles, monitoring, image scanning and independent security review. No compliance, uptime, scale, identity-attestation or exactly-once external execution guarantee is claimed.

## Public release 0.2.0 — 2026-10-08

Windows/Python 3.12.14 local SQLite: 41 tests discovered, 40 pass and the PostgreSQL-only concurrency test is skipped. Branch-inclusive coverage rounds to 87%. Ruff lint/format, Django checks, migration drift and static collection pass. Runtime dependency audit reports no known advisories at this check. PostgreSQL remains the production backend and its concurrency gate must pass in [CI](https://github.com/itzKLAUS/action-ledger/actions/workflows/ci.yml); local SQLite results alone do not establish production correctness.

New regression checks cover owner reconciliation, failed-outcome budget charging, late-worker rejection, idempotent evidence, tenant isolation, bounded export, audit corruption and the operational commands. Git history/tracked files were reviewed and a credential-pattern scan found no matches; that is not a complete security audit. The historical Docker checks above were not repeated on this Windows host, where Docker is unavailable. Workload load tests, independent review, gateway identity controls and deployment-specific backup recovery remain requirements.
