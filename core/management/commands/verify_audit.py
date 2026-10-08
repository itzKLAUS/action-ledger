from django.core.management.base import BaseCommand, CommandError

from core.common import verify
from core.models import Workspace


class Command(BaseCommand):
    help = "Verify one workspace's chained audit, returning a failing exit code on corruption"

    def add_arguments(self, parser):
        parser.add_argument("workspace", type=int)

    def handle(self, *args, **options):
        try:
            workspace = Workspace.objects.get(pk=options["workspace"])
        except Workspace.DoesNotExist as exc:
            raise CommandError("Workspace not found") from exc
        if not verify(workspace):
            raise CommandError("Audit chain INVALID")
        self.stdout.write("Audit chain valid")
