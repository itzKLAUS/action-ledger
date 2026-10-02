import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Budget, Membership, Workspace


class Command(BaseCommand):
    help = "Create a workspace and owner; password is prompted, never accepted as a CLI argument"

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("username")

    @transaction.atomic
    def handle(self, *args, **options):
        if get_user_model().objects.filter(username=options["username"]).exists():
            raise CommandError("User exists; use add_member to enroll existing users")
        password = getpass.getpass("New owner password: ")
        validate_password(password)
        user = get_user_model().objects.create_user(options["username"], password=password)
        workspace = Workspace.objects.create(name=options["name"])
        Membership.objects.create(workspace=workspace, user=user, role="owner")
        Budget.objects.create(workspace=workspace)
        self.stdout.write(f"Created workspace {workspace.pk}")
