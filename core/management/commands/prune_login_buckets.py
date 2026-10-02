import time

from django.core.management.base import BaseCommand

from core.models import LoginBucket


class Command(BaseCommand):
    help = "Remove expired login throttle counters older than 24 hours"

    def handle(self, *args, **options):
        count, _ = LoginBucket.objects.filter(window__lt=int(time.time()) // 900 - 96).delete()
        self.stdout.write(f"Removed {count} expired counters")
