import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings

from .common import verify
from .models import Action, AuditEvent, Budget, Membership, ServiceKey, Workspace
from .services import cancel, complete, create_policy, lease, review, submit


@override_settings(
    SECURE_SSL_REDIRECT=False,
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
)
class WorkflowTests(TestCase):
    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test")
        self.budget = Budget.objects.create(workspace=self.workspace, limit_cents=300)
        self.owner = get_user_model().objects.create_user("owner")
        self.reviewer = get_user_model().objects.create_user("reviewer")
        self.operator = get_user_model().objects.create_user("operator")
        self.om = Membership.objects.create(workspace=self.workspace, user=self.owner, role="owner")
        self.rm = Membership.objects.create(
            workspace=self.workspace, user=self.reviewer, role="reviewer"
        )
        self.tm = Membership.objects.create(
            workspace=self.workspace, user=self.operator, role="operator"
        )
        self.data = {
            "operation": "invoice.send",
            "destination": "billing.example.com",
            "cost_cents": 100,
            "arguments_digest": "a" * 64,
            "idempotency_key": "invoice-1",
        }
        self.policy = create_policy(self.om, {**self.data, "max_cost_cents": 200})
        self.token = "test-only-service-token"
        self.key = ServiceKey.objects.create(
            workspace=self.workspace,
            label="test",
            digest=hashlib.sha256(self.token.encode()).hexdigest(),
        )
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {self.token}"

    def action(self, requester=None, **data):
        return submit(self.workspace, requester or f"user:{self.owner.pk}", {**self.data, **data})[
            0
        ]

    def test_review_lease_and_idempotent_completion(self):
        action = self.action()
        self.assertEqual(action.status, "pending")
        with self.assertRaises(PermissionDenied):
            review(self.om, action.pk, True)
        review(self.rm, action.pk, True)
        token = lease(self.workspace, action.requester, action.pk)
        with self.assertRaises(ValidationError):
            lease(self.workspace, action.requester, action.pk)
        data = {"lease_token": token, "result_digest": "b" * 64, "success": True}
        complete(self.workspace, action.requester, action.pk, data)
        complete(self.workspace, action.requester, action.pk, data)
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.reserved_cents, self.budget.spent_cents), (0, 100))
        self.assertTrue(verify(self.workspace))
        with self.assertRaises(ValidationError):
            complete(self.workspace, action.requester, action.pk, {**data, "success": False})

    def test_unknown_policy_fails_closed(self):
        action = self.action(destination="other.example.com")
        self.assertEqual(action.status, "denied")
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.reserved_cents, 0)

    def test_policy_cost_limit(self):
        self.assertEqual(self.action(cost_cents=201).status, "denied")

    def test_budget_reserves_pending_requests(self):
        self.action(cost_cents=200)
        self.assertEqual(self.action(idempotency_key="next", cost_cents=101).status, "denied")

    def test_rejection_releases_budget(self):
        action = self.action()
        review(self.rm, action.pk, False)
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.reserved_cents, 0)
        with self.assertRaises(ValidationError):
            review(self.rm, action.pk, True)

    def test_cancellation_is_authorized_and_cannot_cancel_leased(self):
        action = self.action()
        with self.assertRaises(PermissionDenied):
            cancel(self.tm, action.pk)
        cancel(self.om, action.pk)
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.reserved_cents, 0)
        action = self.action(idempotency_key="second")
        review(self.rm, action.pk, True)
        lease(self.workspace, action.requester, action.pk)
        with self.assertRaises(ValidationError):
            cancel(self.om, action.pk)

    def test_operator_cannot_review_or_change_policies(self):
        with self.assertRaises(PermissionDenied):
            review(self.tm, self.action().pk, True)
        with self.assertRaises(PermissionDenied):
            create_policy(self.tm, {**self.data, "max_cost_cents": 200})

    def test_policy_revision_invalidates_unleased_approval(self):
        action = self.action()
        review(self.rm, action.pk, True)
        updated = create_policy(self.om, {**self.data, "max_cost_cents": 50})
        self.assertEqual(updated.revision, 2)
        with self.assertRaises(ValidationError):
            lease(self.workspace, action.requester, action.pk)

    def test_auto_approval_policy(self):
        create_policy(self.om, {**self.data, "max_cost_cents": 100, "approval_required": False})
        self.assertEqual(self.action().status, "approved")

    def test_idempotency_preserves_request_and_reservation(self):
        first = self.action()
        self.assertEqual(first.pk, self.action().pk)
        self.assertEqual(Action.objects.count(), 1)
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.reserved_cents, 100)
        with self.assertRaises(ValidationError):
            self.action(cost_cents=101)

    def test_inputs_reject_wildcards_urls_and_invalid_types(self):
        for patch in [
            {"destination": "*.example.com"},
            {"destination": "https://example.com"},
            {"cost_cents": True},
            {"cost_cents": -1},
            {"cost_cents": "100"},
            {"arguments_digest": "invalid"},
            {"operation": "eval()"},
            {"idempotency_key": ""},
        ]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                self.action(**patch)

    def test_wrong_lease_token_rejected(self):
        action = self.action()
        review(self.rm, action.pk, True)
        lease(self.workspace, action.requester, action.pk)
        with self.assertRaises(PermissionDenied):
            complete(
                self.workspace,
                action.requester,
                action.pk,
                {"lease_token": "fake", "result_digest": "b" * 64, "success": True},
            )

    def test_failed_execution_still_charges_reserved_bound(self):
        action = self.action()
        review(self.rm, action.pk, True)
        token = lease(self.workspace, action.requester, action.pk)
        complete(
            self.workspace,
            action.requester,
            action.pk,
            {"lease_token": token, "result_digest": "b" * 64, "success": False},
        )
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.spent_cents, 100)

    def test_audit_tampering_detected(self):
        self.action()
        AuditEvent.objects.filter(kind="action.submitted").update(payload={"fake": True})
        self.assertFalse(verify(self.workspace))

    def test_deleted_audit_tail_detected(self):
        self.action()
        AuditEvent.objects.filter(kind="action.submitted").delete()
        self.assertFalse(verify(self.workspace))

    def test_api_credential_and_csrf_boundary(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        self.assertEqual(
            browser.post(
                "/api/v1/actions/", self.data, content_type="application/json"
            ).status_code,
            401,
        )
        self.assertEqual(browser.post("/action/", {"command": "submit"}).status_code, 403)
        browser.defaults["HTTP_AUTHORIZATION"] = f"Bearer {self.token}"
        response = browser.post("/api/v1/actions/", self.data, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            browser.post(
                "/api/v1/actions/", self.data, content_type="application/json"
            ).status_code,
            200,
        )
        self.key.active = False
        self.key.save()
        self.assertEqual(
            browser.post(
                "/api/v1/actions/", self.data, content_type="application/json"
            ).status_code,
            401,
        )

    def test_service_api_end_to_end(self):
        response = self.client.post("/api/v1/actions/", self.data, content_type="application/json")
        action_id = response.json()["id"]
        review(self.rm, action_id, True)
        url = f"/api/v1/actions/{action_id}/"
        token = self.client.post(url + "lease/").json()["lease_token"]
        response = self.client.post(
            url + "complete/",
            {"lease_token": token, "result_digest": "c" * 64, "success": True},
            content_type="application/json",
        )
        self.assertEqual(response.json()["status"], "succeeded")
        self.assertEqual(self.client.get(url).json()["status"], "succeeded")

    def test_other_service_cannot_access_action(self):
        action = self.action(requester=f"service:{self.key.pk}")
        ServiceKey.objects.create(
            workspace=self.workspace, label="other", digest=hashlib.sha256(b"other").hexdigest()
        )
        self.client.defaults["HTTP_AUTHORIZATION"] = "Bearer other"
        self.assertEqual(self.client.get(f"/api/v1/actions/{action.pk}/").status_code, 404)

    def test_cross_tenant_cannot_review_or_read(self):
        other = Workspace.objects.create(name="Other")
        Budget.objects.create(workspace=other)
        other_member = Membership.objects.create(
            workspace=other, user=self.reviewer, role="reviewer"
        )
        action = self.action()
        with self.assertRaises(Action.DoesNotExist):
            review(other_member, action.pk, True)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(f"/?workspace={other.pk}").status_code, 403)

    def test_dashboard_audit_and_health(self):
        self.client.force_login(self.owner)
        self.action()
        self.assertContains(self.client.get("/"), "Give automation")
        self.assertEqual(self.client.get("/audit/?format=json").json()["verification"], "valid")
        self.assertEqual(self.client.get("/health/").json(), {"status": "ok"})

    def test_json_validation(self):
        for body in ["[]", "not-json", json.dumps({**self.data, "cost_cents": "bad"})]:
            self.assertEqual(
                self.client.post(
                    "/api/v1/actions/", body, content_type="application/json"
                ).status_code,
                400,
            )
        self.assertEqual(self.client.post("/api/v1/actions/", self.data).status_code, 400)


@skipUnless(connection.vendor == "postgresql", "Concurrency contract requires PostgreSQL row locks")
class ConcurrentBudgetTests(TransactionTestCase):
    def test_concurrent_submissions_do_not_overspend(self):
        workspace = Workspace.objects.create(name="Concurrent")
        Budget.objects.create(workspace=workspace, limit_cents=100)
        user = get_user_model().objects.create_user("concurrent")
        membership = Membership.objects.create(workspace=workspace, user=user, role="owner")
        create_policy(
            membership,
            {
                "operation": "invoice.send",
                "destination": "billing.example.com",
                "max_cost_cents": 100,
                "approval_required": False,
            },
        )

        def worker(index):
            close_old_connections()
            try:
                return submit(
                    workspace,
                    "service:test",
                    {
                        "operation": "invoice.send",
                        "destination": "billing.example.com",
                        "cost_cents": 100,
                        "arguments_digest": "a" * 64,
                        "idempotency_key": str(index),
                    },
                )[0].status
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(worker, range(4)))
        self.assertEqual(results.count("approved"), 1)
        self.assertEqual(results.count("denied"), 3)
        self.assertEqual(Budget.objects.get(workspace=workspace).reserved_cents, 100)
        self.assertTrue(verify(workspace))
