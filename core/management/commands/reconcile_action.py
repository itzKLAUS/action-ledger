from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.models import Action, Membership
from core.services import reconcile


class Command(BaseCommand):
    help = "Record a verified downstream outcome without dispatching or replenishing the budget"

    def add_arguments(self, parser):
        parser.add_argument("workspace", type=int)
        parser.add_argument("owner", help="Existing owner username, recorded in the audit")
        parser.add_argument("action")
        parser.add_argument("--outcome", required=True, choices=["succeeded", "failed"])
        parser.add_argument("--evidence-digest", required=True)

    def handle(self, *args, **options):
        try:
            membership = Membership.objects.get(
                workspace_id=options["workspace"], user__username=options["owner"]
            )
            action = reconcile(
                membership,
                options["action"],
                success=options["outcome"] == "succeeded",
                evidence_digest=options["evidence_digest"],
            )
        except (
            Membership.DoesNotExist,
            Action.DoesNotExist,
            PermissionDenied,
            ValidationError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Action {action.pk}: {action.status}; reserved bound charged")
