import uuid

from django.conf import settings
from django.db import models

from .common_models import AuditEvent, LoginBucket, Membership, Workspace  # noqa: F401


class Budget(models.Model):
    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE)
    limit_cents = models.PositiveBigIntegerField(default=10000)
    reserved_cents = models.PositiveBigIntegerField(default=0)
    spent_cents = models.PositiveBigIntegerField(default=0)


class Policy(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    revision = models.PositiveIntegerField()
    operation = models.CharField(max_length=80)
    destination = models.CharField(max_length=253)
    max_cost_cents = models.PositiveIntegerField()
    approval_required = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "operation", "destination", "revision"],
                name="unique_policy_revision",
            )
        ]


class ServiceKey(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    label = models.CharField(max_length=80)
    digest = models.CharField(max_length=64, unique=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Action(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    requester = models.CharField(max_length=160)
    idempotency_key = models.CharField(max_length=100)
    fingerprint = models.CharField(max_length=64)
    operation = models.CharField(max_length=80)
    destination = models.CharField(max_length=253)
    cost_cents = models.PositiveIntegerField()
    arguments_digest = models.CharField(max_length=64)
    policy = models.ForeignKey(Policy, null=True, on_delete=models.PROTECT)
    status = models.CharField(
        max_length=12,
        default="pending",
        choices=[
            (x, x)
            for x in [
                "denied",
                "pending",
                "approved",
                "rejected",
                "leased",
                "succeeded",
                "failed",
                "cancelled",
            ]
        ],
    )
    reason = models.CharField(max_length=200)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    lease_digest = models.CharField(max_length=64, blank=True)
    leased_at = models.DateTimeField(null=True)
    result_digest = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "requester", "idempotency_key"],
                name="unique_action_idempotency",
            )
        ]
        ordering = ["-created_at"]
