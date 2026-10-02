import hashlib
from unittest import TestCase
from unittest.mock import Mock

from sdk import ActionDenied, DecisionPending, LedgerClient


class SDKTests(TestCase):
    def setUp(self):
        self.client = LedgerClient("https://ledger.example.com", "test-only")
        self.args = {
            "operation": "invoice.send",
            "destination": "billing.example.com",
            "cost_cents": 10,
            "arguments": {"invoice_id": "synthetic"},
            "idempotency_key": "invoice-1",
            "callback": Mock(return_value={"ok": True}),
            "persist_lease": Mock(),
        }
        from core.common import canonical

        self.action = {
            "id": "synthetic-id",
            "operation": "invoice.send",
            "destination": "billing.example.com",
            "cost_cents": 10,
            "arguments_digest": hashlib.sha256(
                canonical(self.args["arguments"]).encode()
            ).hexdigest(),
            "status": "approved",
        }

    def test_execute_only_after_matching_decision_and_lease(self):
        self.client.request = Mock(
            side_effect=[self.action, {"lease_token": "fake"}, {"status": "succeeded"}]
        )
        self.assertEqual(self.client.execute(**self.args), {"ok": True})
        self.args["callback"].assert_called_once()
        self.assertEqual(self.client.request.call_count, 3)

    def test_pending_does_not_execute(self):
        self.client.request = Mock(return_value={**self.action, "status": "pending"})
        with self.assertRaises(DecisionPending) as caught:
            self.client.execute(**self.args)
        self.assertEqual(caught.exception.action_id, "synthetic-id")
        self.args["callback"].assert_not_called()

    def test_denied_replayed_or_mismatched_decisions_do_not_execute(self):
        for patch in [
            {"status": "denied"},
            {"status": "leased"},
            {"status": "succeeded"},
            {"destination": "other.example.com"},
        ]:
            with self.subTest(patch=patch):
                self.client.request = Mock(return_value={**self.action, **patch})
                with self.assertRaises(ActionDenied):
                    self.client.execute(**self.args)
        self.args["callback"].assert_not_called()

    def test_lease_failure_prevents_callback(self):
        self.client.request = Mock(side_effect=[self.action, ActionDenied("lease failed")])
        with self.assertRaises(ActionDenied):
            self.client.execute(**self.args)
        self.args["callback"].assert_not_called()

    def test_failed_callback_records_failure_and_never_retries(self):
        self.client.request = Mock(side_effect=[self.action, {"lease_token": "fake"}, {}])
        self.args["callback"].side_effect = RuntimeError("synthetic")
        with self.assertRaises(RuntimeError):
            self.client.execute(**self.args)
        self.assertFalse(self.client.request.call_args.args[1]["success"])
        self.args["callback"].assert_called_once()

    def test_insecure_origins_and_redirects_rejected(self):
        for origin in [
            "http://remote.example.com",
            "https://user:secret@example.com",
            "https://example.com/?key=value",
            "https://example.com/path",
        ]:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                LedgerClient(origin, "test-only", allow_local_http=True)
        LedgerClient("http://127.0.0.1:8000", "test-only", allow_local_http=True)

    def test_checkpoint_failure_prevents_callback(self):
        self.client.request = Mock(side_effect=[self.action, {"lease_token": "fake"}])
        self.args["persist_lease"].side_effect = RuntimeError("checkpoint unavailable")
        with self.assertRaises(RuntimeError):
            self.client.execute(**self.args)
        self.args["callback"].assert_not_called()
