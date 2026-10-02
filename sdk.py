"""Standard-library Action Ledger client; no provider API key or model dependency."""

import hashlib
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class DecisionPending(Exception):
    """Persist action_id; a later invocation with the SAME key resumes after review."""

    def __init__(self, action_id):
        self.action_id = action_id
        super().__init__(f"Action {action_id} is awaiting review")


class ActionDenied(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LedgerClient:
    def __init__(self, base_url, service_key, *, allow_local_http=False):
        parsed = urlsplit(base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use an origin URL without credentials, query, or fragment")
        if not parsed.hostname or parsed.path not in ("", "/"):
            raise ValueError("Use an origin URL")
        if parsed.scheme != "https" and not (
            allow_local_http
            and parsed.scheme == "http"
            and parsed.hostname in ("localhost", "127.0.0.1")
        ):
            raise ValueError(
                "HTTPS is required; HTTP is allowed only for explicit local development"
            )
        self.base_url, self.service_key = base_url.rstrip("/"), service_key
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path, data=None):
        body = json.dumps(data, allow_nan=False).encode() if data is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers={
                "Authorization": f"Bearer {self.service_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with self.opener.open(request, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # Do not copy response bodies or credential-bearing Request objects into errors.
            raise ActionDenied(f"Ledger rejected request (HTTP {exc.code})") from None

    def execute(
        self,
        *,
        operation,
        destination,
        cost_cents,
        arguments,
        idempotency_key,
        callback,
        persist_lease,
    ):
        """Execute a trusted local callback at most once per server-issued lease.

        A callback must honor destination/cost boundaries itself. If the process dies after
        execution, reconcile externally; never automatically repeat the external action.
        """
        encoded = json.dumps(
            arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
        fingerprint = hashlib.sha256(encoded).hexdigest()
        action = self.request(
            "/api/v1/actions/",
            {
                "operation": operation,
                "destination": destination,
                "cost_cents": cost_cents,
                "arguments_digest": fingerprint,
                "idempotency_key": idempotency_key,
            },
        )
        if any(
            action.get(k) != v
            for k, v in {
                "operation": operation,
                "destination": destination,
                "cost_cents": cost_cents,
                "arguments_digest": fingerprint,
            }.items()
        ):
            raise ActionDenied("Ledger decision does not match the requested action")
        if action["status"] == "pending":
            raise DecisionPending(action["id"])
        if action["status"] != "approved":
            raise ActionDenied(f"Action is {action['status']}; no callback executed")
        path = f"/api/v1/actions/{action['id']}/"
        token = self.request(path + "lease/", {})["lease_token"]
        snapshot = json.loads(encoded)
        # This must commit durably before the callback; failure leaves the lease parked.
        persist_lease(action, token, snapshot)
        try:
            result = callback(snapshot)
            digest = hashlib.sha256(
                json.dumps(
                    result,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode()
            ).hexdigest()
        except Exception:
            # A constant synthetic digest records failure without leaking tool errors.
            self.request(
                path + "complete/",
                {
                    "lease_token": token,
                    "success": False,
                    "result_digest": hashlib.sha256(b"callback-failed").hexdigest(),
                },
            )
            raise
        self.request(
            path + "complete/", {"lease_token": token, "success": True, "result_digest": digest}
        )
        return result
