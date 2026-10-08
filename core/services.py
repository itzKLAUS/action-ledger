import hashlib
import re
import secrets

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .common import canonical, record, require
from .models import Action, Budget, Policy, Workspace

DIGEST = re.compile(r"[0-9a-f]{64}\Z")
OPERATION = re.compile(r"[a-z][a-z0-9_.-]{0,79}\Z")
HOST = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z")


def validate_int(value, name, maximum=100000000):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValidationError(f"{name} must be an integer from 0 to {maximum}")
    return value


def validate_target(operation, destination):
    if not isinstance(operation, str) or not OPERATION.fullmatch(operation):
        raise ValidationError("Invalid operation identifier")
    if not isinstance(destination, str) or not HOST.fullmatch(destination):
        raise ValidationError(
            "Destination must be an exact lowercase DNS hostname, without URL or port"
        )


@transaction.atomic
def create_policy(membership, data):
    require(membership, ["owner"])
    workspace = Workspace.objects.select_for_update().get(pk=membership.workspace_id)
    operation, destination = data.get("operation"), data.get("destination")
    validate_target(operation, destination)
    cost = validate_int(data.get("max_cost_cents"), "max_cost_cents")
    approval = data.get("approval_required", True)
    if type(approval) is not bool:
        raise ValidationError("approval_required must be boolean")
    previous = Policy.objects.filter(
        workspace=workspace, operation=operation, destination=destination
    )
    revision = max(previous.values_list("revision", flat=True), default=0) + 1
    previous.update(active=False)
    policy = Policy.objects.create(
        workspace=workspace,
        operation=operation,
        destination=destination,
        revision=revision,
        max_cost_cents=cost,
        approval_required=approval,
    )
    record(
        workspace,
        "policy.created",
        membership.user.username,
        {
            "policy": policy.pk,
            "revision": revision,
            "operation": operation,
            "destination": destination,
        },
    )
    return policy


@transaction.atomic
def submit(workspace, requester, data):
    workspace = Workspace.objects.select_for_update().get(pk=workspace.pk)
    operation, destination = data.get("operation"), data.get("destination")
    validate_target(operation, destination)
    cost = validate_int(data.get("cost_cents"), "cost_cents")
    args = data.get("arguments_digest")
    if not isinstance(args, str) or not DIGEST.fullmatch(args):
        raise ValidationError("arguments_digest must be a lowercase SHA-256 digest")
    key = data.get("idempotency_key")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", key):
        raise ValidationError("Invalid idempotency_key")
    fingerprint = hashlib.sha256(
        canonical([operation, destination, cost, args]).encode()
    ).hexdigest()
    existing = Action.objects.filter(
        workspace=workspace, requester=requester, idempotency_key=key
    ).first()
    if existing:
        if existing.fingerprint != fingerprint:
            raise ValidationError("Idempotency key already used with different arguments")
        return existing, False
    policy = Policy.objects.filter(
        workspace=workspace, operation=operation, destination=destination, active=True
    ).first()
    budget = Budget.objects.get(workspace=workspace)
    status, reason = "denied", "No matching policy"
    if policy:
        if cost > policy.max_cost_cents:
            reason = "Per-action cost limit exceeded"
        elif cost + budget.reserved_cents + budget.spent_cents > budget.limit_cents:
            reason = "Workspace budget exhausted"
        else:
            status = "pending" if policy.approval_required else "approved"
            reason = "Review required" if policy.approval_required else "Policy allows action"
            budget.reserved_cents += cost
            budget.save(update_fields=["reserved_cents"])
    action = Action.objects.create(
        workspace=workspace,
        requester=requester,
        idempotency_key=key,
        fingerprint=fingerprint,
        operation=operation,
        destination=destination,
        cost_cents=cost,
        arguments_digest=args,
        policy=policy,
        status=status,
        reason=reason,
    )
    record(
        workspace,
        "action.submitted",
        requester,
        {"action": str(action.pk), "status": status, "cost_cents": cost, "arguments_digest": args},
    )
    return action, True


@transaction.atomic
def review(membership, action_id, approve):
    require(membership, ["owner", "reviewer"])
    workspace = Workspace.objects.select_for_update().get(pk=membership.workspace_id)
    action = Action.objects.get(pk=action_id, workspace=workspace)
    if action.requester == f"user:{membership.user.pk}":
        raise PermissionDenied("A different person must review this action")
    if action.status != "pending":
        raise ValidationError("Action is no longer pending")
    action.status = "approved" if approve else "rejected"
    action.reviewed_by = membership.user
    action.reason = "Approved by reviewer" if approve else "Rejected by reviewer"
    action.save(update_fields=["status", "reviewed_by", "reason"])
    if not approve:
        budget = Budget.objects.get(workspace=workspace)
        budget.reserved_cents -= action.cost_cents
        budget.save(update_fields=["reserved_cents"])
    record(
        workspace,
        "action.reviewed",
        membership.user.username,
        {"action": str(action.pk), "approved": approve},
    )
    return action


@transaction.atomic
def lease(workspace, requester, action_id):
    workspace = Workspace.objects.select_for_update().get(pk=workspace.pk)
    action = Action.objects.get(pk=action_id, workspace=workspace, requester=requester)
    if action.status != "approved":
        raise ValidationError("Only an approved, unleased action can be leased")
    if not action.policy.active:
        raise ValidationError("Policy changed; cancel this action and submit again")
    token = secrets.token_urlsafe(32)
    action.status, action.lease_digest, action.leased_at = (
        "leased",
        hashlib.sha256(token.encode()).hexdigest(),
        timezone.now(),
    )
    action.save(update_fields=["status", "lease_digest", "leased_at"])
    record(workspace, "action.leased", requester, {"action": str(action.pk)})
    return token


@transaction.atomic
def complete(workspace, requester, action_id, data):
    workspace = Workspace.objects.select_for_update().get(pk=workspace.pk)
    action = Action.objects.get(pk=action_id, workspace=workspace, requester=requester)
    token, result = data.get("lease_token"), data.get("result_digest")
    if (
        not isinstance(token, str)
        or len(token) > 100
        or not secrets.compare_digest(
            action.lease_digest, hashlib.sha256(token.encode()).hexdigest()
        )
    ):
        raise PermissionDenied("Invalid execution lease")
    if (
        not isinstance(result, str)
        or not DIGEST.fullmatch(result)
        or type(data.get("success")) is not bool
    ):
        raise ValidationError("Provide success boolean and SHA-256 result_digest")
    if action.status in ("succeeded", "failed"):
        if action.result_digest == result and (action.status == "succeeded") == data["success"]:
            return action
        raise ValidationError("Completion conflicts with recorded result")
    if action.status != "leased":
        raise ValidationError("Action is not leased")
    action.status = "succeeded" if data["success"] else "failed"
    action.result_digest = result
    action.save(update_fields=["status", "result_digest"])
    budget = Budget.objects.get(workspace=workspace)
    budget.reserved_cents -= action.cost_cents
    # Charge the declared bound even on failure; uncertainty must not replenish the budget.
    budget.spent_cents += action.cost_cents
    budget.save(update_fields=["reserved_cents", "spent_cents"])
    record(
        workspace,
        "action.completed",
        requester,
        {"action": str(action.pk), "status": action.status, "result_digest": result},
    )
    return action


@transaction.atomic
def cancel(membership, action_id):
    workspace = Workspace.objects.select_for_update().get(pk=membership.workspace_id)
    action = Action.objects.get(workspace=workspace, pk=action_id)
    if membership.role != "owner" and action.requester != f"user:{membership.user.pk}":
        raise PermissionDenied
    if action.status not in ("pending", "approved"):
        raise ValidationError("Only unleased requests may be cancelled")
    action.status = "cancelled"
    action.save(update_fields=["status"])
    budget = Budget.objects.get(workspace=workspace)
    budget.reserved_cents -= action.cost_cents
    budget.save(update_fields=["reserved_cents"])
    record(workspace, "action.cancelled", membership.user.username, {"action": str(action.pk)})


@transaction.atomic
def reconcile(membership, action_id, *, success, evidence_digest):
    """Owner records a checked downstream outcome; never execute the action again.

    Charge the full reserved bound even on failure. The evidence digest commits to
    an independently collected receipt, not proof that this service inspected it.
    """
    require(membership, ["owner"])
    if type(success) is not bool or not isinstance(evidence_digest, str):
        raise ValidationError("Provide a success boolean and evidence SHA-256 digest")
    if not DIGEST.fullmatch(evidence_digest):
        raise ValidationError("Provide a lowercase evidence SHA-256 digest")
    workspace = Workspace.objects.select_for_update().get(pk=membership.workspace_id)
    action = Action.objects.get(workspace=workspace, pk=action_id)
    previous = workspace.auditevent_set.filter(
        kind="action.reconciled", payload__action=str(action.pk)
    ).first()
    if previous:
        if (
            previous.payload["success"] == success
            and previous.payload["evidence_digest"] == evidence_digest
        ):
            return action
        raise ValidationError("Reconciliation conflicts with recorded evidence")
    if action.status != "leased":
        raise ValidationError(
            "Only a leased action with a checked downstream outcome can be reconciled"
        )
    action.status = "succeeded" if success else "failed"
    action.result_digest = evidence_digest
    # Invalidate the old worker token so a late acknowledgement cannot overwrite evidence.
    action.lease_digest = ""
    action.reason = "Downstream outcome reconciled by owner"
    action.save(update_fields=["status", "result_digest", "lease_digest", "reason"])
    budget = Budget.objects.get(workspace=workspace)
    budget.reserved_cents -= action.cost_cents
    budget.spent_cents += action.cost_cents
    budget.save(update_fields=["reserved_cents", "spent_cents"])
    record(
        workspace,
        "action.reconciled",
        membership.user.username,
        {
            "action": str(action.pk),
            "success": success,
            "evidence_digest": evidence_digest,
            "charged_cents": action.cost_cents,
        },
    )
    return action
