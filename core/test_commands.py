from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from .models import Membership, ServiceKey, Workspace


class ProvisioningTests(TestCase):
    def test_prompted_provisioning_and_existing_membership_update(self):
        with patch("getpass.getpass", return_value="synthetic-test-only-password-9876"):
            call_command("bootstrap_workspace", "Test", "owner", stdout=StringIO())
            workspace = Workspace.objects.get()
            call_command("add_member", workspace.pk, "reviewer", "reviewer", stdout=StringIO())
        self.assertTrue(
            get_user_model()
            .objects.get(username="owner")
            .check_password("synthetic-test-only-password-9876")
        )
        call_command("add_member", workspace.pk, "reviewer", "operator", stdout=StringIO())
        self.assertEqual(Membership.objects.get(user__username="reviewer").role, "operator")
        with self.assertRaises(CommandError):
            call_command("bootstrap_workspace", "Other", "owner", stdout=StringIO())

    def test_key_issuance_hashes_secret_and_revocation(self):
        workspace = Workspace.objects.create(name="Test")
        output = StringIO()
        with patch("secrets.token_urlsafe", return_value="synthetic-test-token-only"):
            call_command("service_key", workspace.pk, "test", stdout=output)
        key = ServiceKey.objects.get()
        self.assertNotEqual(key.digest, "synthetic-test-token-only")
        self.assertIn("synthetic-test-token-only", output.getvalue())
        call_command("service_key", workspace.pk, "test", revoke=key.pk, stdout=StringIO())
        key.refresh_from_db()
        self.assertFalse(key.active)

    @override_settings(DEBUG=False)
    def test_demo_cannot_run_in_production(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
