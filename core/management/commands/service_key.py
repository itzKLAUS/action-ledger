import hashlib
import secrets

from django.core.management.base import BaseCommand

from core.models import ServiceKey, Workspace


class Command(BaseCommand):
    help = "Issue or revoke a workspace service key; issuance prints its secret once"

    def add_arguments(self, parser):
        parser.add_argument("workspace", type=int)
        parser.add_argument("label")
        parser.add_argument("--revoke", type=int)

    def handle(self, *args, **options):
        workspace = Workspace.objects.get(pk=options["workspace"])
        if options["revoke"]:
            ServiceKey.objects.filter(pk=options["revoke"], workspace=workspace).update(
                active=False
            )
            self.stdout.write("Revoked")
            return
        token = secrets.token_urlsafe(32)
        key = ServiceKey.objects.create(
            workspace=workspace,
            label=options["label"],
            digest=hashlib.sha256(token.encode()).hexdigest(),
        )
        self.stdout.write(f"Key ID: {key.pk}; secret (store securely): {token}")
