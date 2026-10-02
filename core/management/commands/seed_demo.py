import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Budget, Membership, Workspace
from core.services import complete, create_policy, lease, submit


class Command(BaseCommand):
    help = "Seed synthetic local demo data; never enabled in production"

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo seeding requires APP_DEBUG=1")
        password = os.getenv("DEMO_PASSWORD", "")
        if len(password) < 16:
            raise CommandError("Set DEMO_PASSWORD to at least 16 characters")
        if Workspace.objects.exists():
            raise CommandError("Demo seeding requires an empty database")
        owner = get_user_model().objects.create_user("demo-owner", password=password)
        reviewer = get_user_model().objects.create_user("demo-reviewer", password=password)
        workspace = Workspace.objects.create(name="Northstar Operations")
        owner_member = Membership.objects.create(workspace=workspace, user=owner, role="owner")
        Membership.objects.create(workspace=workspace, user=reviewer, role="reviewer")

        Budget.objects.create(workspace=workspace, limit_cents=25000)
        create_policy(
            owner_member,
            {
                "operation": "invoice.send",
                "destination": "billing.example.com",
                "max_cost_cents": 500,
                "approval_required": True,
            },
        )
        create_policy(
            owner_member,
            {
                "operation": "report.publish",
                "destination": "reports.example.com",
                "max_cost_cents": 50,
                "approval_required": False,
            },
        )
        submit(
            workspace,
            f"user:{owner.pk}",
            {
                "operation": "invoice.send",
                "destination": "billing.example.com",
                "cost_cents": 120,
                "arguments_digest": "a" * 64,
                "idempotency_key": "demo-invoice",
            },
        )
        submit(
            workspace,
            f"user:{owner.pk}",
            {
                "operation": "invoice.send",
                "destination": "unknown.example.com",
                "cost_cents": 120,
                "arguments_digest": "a" * 64,
                "idempotency_key": "demo-denied",
            },
        )
        action, _ = submit(
            workspace,
            f"user:{owner.pk}",
            {
                "operation": "report.publish",
                "destination": "reports.example.com",
                "cost_cents": 25,
                "arguments_digest": "b" * 64,
                "idempotency_key": "demo-report",
            },
        )
        token = lease(workspace, action.requester, action.pk)
        complete(
            workspace,
            action.requester,
            action.pk,
            {"lease_token": token, "result_digest": "c" * 64, "success": True},
        )

        self.stdout.write(
            "Synthetic demo created. Sign in as demo-owner or demo-reviewer using DEMO_PASSWORD."
        )
