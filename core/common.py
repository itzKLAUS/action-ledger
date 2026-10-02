import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse

from .models import AuditEvent, Membership, Workspace


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_event(previous, sequence, kind, actor, payload):
    return hashlib.sha256(
        canonical([previous, sequence, kind, actor, payload]).encode()
    ).hexdigest()


@transaction.atomic
def record(workspace, kind, actor, payload):
    # All services acquire this same workspace row before mutating domain state.
    workspace = Workspace.objects.select_for_update().get(pk=workspace.pk)
    seq = workspace.audit_sequence + 1
    digest = digest_event(workspace.audit_head, seq, kind, str(actor), payload)
    AuditEvent.objects.create(
        workspace=workspace,
        sequence=seq,
        kind=kind,
        actor=str(actor),
        payload=payload,
        previous=workspace.audit_head,
        digest=digest,
    )
    workspace.audit_sequence, workspace.audit_head = seq, digest
    workspace.save(update_fields=["audit_sequence", "audit_head"])


@transaction.atomic
def verify(workspace):
    workspace = Workspace.objects.select_for_update().get(pk=workspace.pk)
    previous = "0" * 64
    sequence = 0
    for event in AuditEvent.objects.filter(workspace=workspace):
        sequence += 1
        if event.sequence != sequence or event.previous != previous:
            return False
        if event.digest != digest_event(previous, sequence, event.kind, event.actor, event.payload):
            return False
        previous = event.digest
    return sequence == workspace.audit_sequence and previous == workspace.audit_head


def member(request):
    if not request.user.is_authenticated:
        raise PermissionDenied
    # Explicit workspace selection is validated against membership, never client-supplied alone.
    workspace_id = request.GET.get("workspace") or request.POST.get("workspace")
    if workspace_id and (not workspace_id.isdecimal() or len(workspace_id) > 18):
        raise PermissionDenied("Invalid workspace")
    query = Membership.objects.filter(user=request.user).select_related("workspace")
    membership = query.filter(workspace_id=workspace_id).first() if workspace_id else query.first()
    if membership is None:
        raise PermissionDenied
    return membership


def require(membership, roles):
    if membership.role not in roles:
        raise PermissionDenied("This role cannot perform the requested action")


def json_body(request):
    if request.content_type != "application/json":
        raise ValidationError("Content-Type must be application/json")
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("Invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValidationError("Expected a JSON object")
    return data


def error_response(exc):
    return JsonResponse({"error": "; ".join(exc.messages)}, status=400)
