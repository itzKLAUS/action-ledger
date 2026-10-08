from io import StringIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from . import tests as workflow_fixtures
from .common import verify
from .models import Action, AuditEvent, Membership, Workspace
from .services import complete, lease, reconcile, review


@override_settings(
    SECURE_SSL_REDIRECT=False,
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
)
class RecoveryTests(TestCase):
    setUp = workflow_fixtures.WorkflowTests.setUp
    action = workflow_fixtures.WorkflowTests.action

    def leased(self):
        action = self.action()
        review(self.rm, action.pk, True)
        token = lease(self.workspace, action.requester, action.pk)
        return action, token

    def test_reconciled_outcome_is_idempotent_and_charged(self):
        action, token = self.leased()
        for _ in range(2):
            result = reconcile(self.om, action.pk, success=True, evidence_digest="c" * 64)
            self.assertEqual(result.status, "succeeded")
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.reserved_cents, self.budget.spent_cents), (0, 100))
        self.assertEqual(AuditEvent.objects.filter(kind="action.reconciled").count(), 1)
        self.assertTrue(verify(self.workspace))
        with self.assertRaises(PermissionDenied):
            complete(
                self.workspace,
                action.requester,
                action.pk,
                {"lease_token": token, "success": True, "result_digest": "c" * 64},
            )
        with self.assertRaises(ValidationError):
            reconcile(self.om, action.pk, success=False, evidence_digest="c" * 64)

    def test_failed_outcome_does_not_replenish_budget(self):
        action, _ = self.leased()
        reconcile(self.om, action.pk, success=False, evidence_digest="d" * 64)
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.spent_cents, 100)
        self.assertEqual(self.budget.reserved_cents, 0)
        with self.assertRaises(ValidationError):
            lease(self.workspace, action.requester, action.pk)

    def test_recovery_authorization_validation_and_tenant_isolation(self):
        action, _ = self.leased()
        for membership in [self.rm, self.tm]:
            with self.assertRaises(PermissionDenied):
                reconcile(membership, action.pk, success=True, evidence_digest="a" * 64)
        for success, digest in [(1, "a" * 64), (True, "bad"), (True, None)]:
            with self.assertRaises(ValidationError):
                reconcile(self.om, action.pk, success=success, evidence_digest=digest)
        other = Workspace.objects.create(name="Other")
        membership = Membership.objects.create(workspace=other, user=self.owner, role="owner")
        with self.assertRaises(Action.DoesNotExist):
            reconcile(membership, action.pk, success=True, evidence_digest="a" * 64)
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.reserved_cents, 100)

    def test_pending_cannot_be_reconciled(self):
        with self.assertRaises(ValidationError):
            reconcile(self.om, self.action().pk, success=True, evidence_digest="a" * 64)

    def test_reconciliation_command(self):
        action, _ = self.leased()
        output = StringIO()
        call_command(
            "reconcile_action",
            self.workspace.pk,
            self.owner.username,
            str(action.pk),
            outcome="succeeded",
            evidence_digest="a" * 64,
            stdout=output,
        )
        self.assertIn("succeeded", output.getvalue())

    def test_audit_pagination_and_validation(self):
        self.action()
        self.client.force_login(self.owner)
        first = self.client.get("/audit/?format=json&limit=1").json()
        self.assertEqual(len(first["events"]), 1)
        self.assertTrue(first["has_more"])
        second = self.client.get(f"/audit/?format=json&after={first['next_after']}").json()
        self.assertGreater(second["events"][0]["sequence"], first["next_after"])
        self.assertFalse(second["has_more"])
        for query in ["limit=0", "limit=1001", "after=-1", "after=x"]:
            self.assertEqual(self.client.get(f"/audit/?format=json&{query}").status_code, 400)

    def test_audit_verification_command_detects_corruption(self):
        output = StringIO()
        call_command("verify_audit", self.workspace.pk, stdout=output)
        self.assertIn("valid", output.getvalue())
        AuditEvent.objects.filter(workspace=self.workspace).update(digest="f" * 64)
        with self.assertRaises(CommandError):
            call_command("verify_audit", self.workspace.pk)
