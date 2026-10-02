# Verification — 2026-10-01

Local checks were executed in Docker with synthetic data and no production credentials. Test containers had no external network or host credentials. PostgreSQL tests used an internal Docker network with a disposable database; previews and a pinned browser tool used a separate internal network.

- PostgreSQL 17, Python 3.12: **34 tests pass**, no skipped tests. Includes competing budget submissions, idempotent intent/completion, single leases, invalid costs/hosts, own-request review rejection, tenant/service isolation, credential revocation, CSRF, login throttling, provisioning and SDK checkpoint failures.
- Branch-inclusive coverage, excluding tests and migrations: **86%** across core and SDK. This is measured test coverage, not a security guarantee.
- Ruff lint and format checks pass; migration drift check reports no changes; Django system checks report no issues.
- Production image builds as a non-root runtime user with hash-checked dependencies. `check --deploy --fail-level WARNING` reports no issues with production settings and a synthetic long secret.
- Production image smoke check renders login over simulated HTTPS, redirects HTTP and serves hashed CSS successfully.
- Real SDK-to-HTTP smoke workflow: submit → approve via auto-allow policy → lease → checkpoint hook → synthetic callback → completion. Replaying the completed intent executes no callback.
- Browser sign-in succeeds; an owner cannot approve their own pending request; a separate reviewer can approve it and the queue updates.
- Runtime Python dependency audit reports no known vulnerabilities. Container OS scanning and independent review are not complete.

The production image check did not connect to a production database or TLS proxy. PostgreSQL workflow tests separately exercised the data contract. CI is configured for Python 3.12/3.13 and PostgreSQL; remote CI has not run because repository creation is access-blocked. Python 3.13 has not been executed locally.

Open deployment requirements: trusted TLS proxy, gateway MFA/SSO, workload-specific load tests, backup/restore exercise, secret rotation, least-privilege database roles, monitoring, image scanning and independent security review. No compliance, uptime, scale, identity-attestation or exactly-once external execution guarantee is claimed.
