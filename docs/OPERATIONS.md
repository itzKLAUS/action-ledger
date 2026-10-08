# Operations

## Local development

Use Python 3.12+ and uv, or Docker Compose. `uv sync --locked` installs the reviewed lock. Generate `APP_SECRET_KEY` independently for each installation. Set `APP_DEBUG=1` only for localhost. SQLite is for sequential local demos; production fails to start without PostgreSQL.

```sh
export APP_DEBUG=1
export APP_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
uv sync --locked
uv run python manage.py migrate
uv run python manage.py bootstrap_workspace "Operations" owner
uv run python manage.py add_member 1 reviewer reviewer
uv run python manage.py runserver 127.0.0.1:8000
```

Passwords are prompted and validated; don't put them in shell arguments. CLI provisioning requires trusted deployment access. Existing users can be enrolled in multiple workspaces. Select an authorized workspace with `?workspace=ID`; forms preserve it.

For a synthetic local demo in a NEW database, set `DEMO_PASSWORD` to a generated value of at least 16 characters and run `uv run python manage.py seed_demo`. Sign in as `demo-owner` or `demo-reviewer`. The command rejects production and non-empty databases.

## Containers

Copy `.env.example` to `.env`, replace both placeholders with independently generated secrets, then:

```sh
docker compose build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py bootstrap_workspace "Operations" owner
docker compose run --rm web python manage.py add_member 1 reviewer reviewer
docker compose up -d
```

Set `APP_PORT` separately when running multiple apps on the same machine. Compose binds HTTP to localhost and uses PostgreSQL without a published database port. The production override is:

```sh
docker compose -f compose.yaml -f compose.production.yaml up -d
```

Configure a TLS reverse proxy first. It must overwrite/strip client-provided `X-Forwarded-Proto` before `APP_TRUST_PROXY=1` is enabled. Set an exact hostname and HTTPS CSRF origin. Do not expose gunicorn directly. The application enforces shared PostgreSQL login counters: 10 attempts per username and 250 per source address in a 15-minute window. All attempts count, including successful ones. Gateway request/body limits and abuse monitoring are still required. REMOTE_ADDR is the counter source; do not trust arbitrary forwarded-IP headers. A proxy or large NAT shares an address, so enforce client-aware throttling at the gateway too. Run `prune_login_buckets` daily to remove expired counters. Enable multi-factor authentication at the access gateway, or implement reviewed SSO before broader enterprise access.

## Deployment gates

1. `make check` against PostgreSQL, and `APP_DEBUG=0 uv run python manage.py check --deploy --fail-level WARNING` with deployment variables.
2. Restore a PostgreSQL backup into an isolated environment and rerun audit verification. Choose retention, recovery-point and recovery-time objectives; none are asserted by this repository.
3. Restrict database/admin access and provision least-privilege runtime credentials. Use a separate migration role in production. The Compose example uses one role for convenience.
4. Store secrets in an organization-approved secret manager. Plan rotation and revoke old service keys. Sessions last one hour. Review access regularly and remove memberships promptly.
5. Enforce login throttling, TLS and gateway MFA; configure monitoring for 5xx, database failures, repeated 403/401 and integrity failures. Don't log Authorization, cookies, passwords, JSON request bodies, tool arguments or knowledge content.
6. Run dependency scanning and image scanning. `pip-audit` covers Python package advisories, not container OS packages or undiscovered flaws. Update digests/locks through reviewed changes.
7. Perform an independent security review and workload-specific load test. No uptime, throughput, compliance or horizontal-scale claim is made here.

## Audit limitations

Services append sequence-numbered SHA-256 chains under the workspace row lock. Verification detects missing, reordered or changed events against the stored head. Event kind, actor, payload and sequence are hashed; display timestamps are informational. A database administrator can rewrite the full chain and head. For stronger evidence, export and anchor heads in independently controlled append-only storage. That external anchoring is not implemented.

## Availability and recovery

`GET /health/` checks database connectivity. Run migrations as a separate deployment step; do not race them in every web worker. Check integrity failures before reactivation or serving data. Retain old revisions and approved releases. Avoid deleting audit or domain rows manually. Read-only containers use a writable temporary directory; user documents remain in PostgreSQL.

## Development verification

`make check` performs Ruff lint/format checks, migration drift detection, Django checks, tests and coverage. CI runs PostgreSQL and Python 3.12/3.13, with read-only GitHub token permissions and full-SHA action pins. See GitHub Actions for verification against the current commit.

## Reconcile a stranded execution

First stop the affected worker and collect independent downstream evidence. A timeout alone cannot establish whether the action succeeded. If the outcome is still unknown, keep the reservation and investigate; do not mark failure to reclaim spending capacity.

```sh
uv run python manage.py reconcile_action WORKSPACE_ID OWNER_USERNAME ACTION_UUID --outcome succeeded --evidence-digest SHA256_OF_VERIFIED_EVIDENCE
uv run python manage.py verify_audit WORKSPACE_ID
```

Run these commands only from trusted deployment access. The username identifies an existing owner; it is an audit label, not CLI authentication. The command records an evidence digest, invalidates the old execution token, and charges the entire reserved bound for either outcome. It never invokes an external tool or automatically retries the action. Identical evidence/outcome is idempotent; conflicting evidence is rejected. Preserve the original evidence in independently controlled storage.

Audit JSON exports accept `?format=json&after=0&limit=100`, with `next_after` and `has_more`; the maximum page is 1000. Verification still checks the entire workspace chain and can be expensive on large histories. The export is a live scan, not a snapshot; database owners remain able to rewrite history.

On Windows PowerShell, initialize local development variables with:

```powershell
$env:APP_DEBUG = "1"
$env:APP_SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(48))"
```
