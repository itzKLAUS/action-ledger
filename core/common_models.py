from django.conf import settings
from django.db import models


class Workspace(models.Model):
    name = models.CharField(max_length=100)
    audit_sequence = models.PositiveBigIntegerField(default=0)
    audit_head = models.CharField(max_length=64, default="0" * 64)


class Membership(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(
        max_length=10,
        choices=[("owner", "Owner"), ("reviewer", "Reviewer"), ("operator", "Operator")],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "user"], name="unique_membership")
        ]


class AuditEvent(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    sequence = models.PositiveBigIntegerField()
    kind = models.CharField(max_length=50)
    actor = models.CharField(max_length=150)
    payload = models.JSONField()
    previous = models.CharField(max_length=64)
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "sequence"], name="unique_audit_sequence")
        ]
        ordering = ["sequence"]


class LoginBucket(models.Model):
    key = models.CharField(max_length=64)
    window = models.PositiveBigIntegerField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["key", "window"], name="unique_login_bucket")
        ]
