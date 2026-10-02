import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Membership, Workspace


class Command(BaseCommand):
    help = "Enroll a user; creates the account with a prompted password if needed"

    def add_arguments(self, parser):
        parser.add_argument("workspace", type=int)
        parser.add_argument("username")
        parser.add_argument("role", choices=["owner", "reviewer", "operator"])

    @transaction.atomic
    def handle(self, *args, **options):
        workspace = Workspace.objects.get(pk=options["workspace"])
        user = get_user_model().objects.filter(username=options["username"]).first()
        if not user:
            password = getpass.getpass("New user password: ")
            validate_password(password)
            user = get_user_model().objects.create_user(options["username"], password=password)
        Membership.objects.update_or_create(
            workspace=workspace, user=user, defaults={"role": options["role"]}
        )
        self.stdout.write("Membership saved")
