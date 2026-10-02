import hashlib

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .common import error_response, json_body, member
from .models import Action, Budget, Policy, ServiceKey
from .services import cancel, complete, create_policy, lease, review, submit


@login_required
@require_GET
def dashboard(request):
    membership = member(request)
    actions = Action.objects.filter(workspace=membership.workspace)
    return render(
        request,
        "dashboard.html",
        {
            "membership": membership,
            "actions": actions[:100],
            "pending": actions.filter(status="pending").count(),
            "completed": actions.filter(status="succeeded").count(),
            "budget": Budget.objects.get(workspace=membership.workspace),
            "policies": Policy.objects.filter(workspace=membership.workspace, active=True),
        },
    )


@login_required
@require_POST
def browser_action(request):
    membership = member(request)
    data = request.POST.dict()
    try:
        command = data.get("command")
        if command == "policy":
            data["max_cost_cents"] = int(data.get("max_cost_cents", ""))
            data["approval_required"] = "approval_required" in data
            create_policy(membership, data)
            messages.success(
                request,
                "Policy revision saved. Earlier revisions cannot authorize new execution leases.",
            )
        elif command == "submit":
            data["cost_cents"] = int(data.get("cost_cents", ""))
            action, _ = submit(membership.workspace, f"user:{request.user.pk}", data)
            messages.success(request, f"Request {action.pk}: {action.status} — {action.reason}")
        elif command in ("approve", "reject"):
            review(membership, data.get("action"), command == "approve")
            messages.success(request, "Review recorded.")
        elif command == "cancel":
            cancel(membership, data.get("action"))
            messages.success(request, "Request cancelled; reservation released.")
        else:
            raise ValidationError("Unknown command")
    except (ValidationError, ValueError) as exc:
        messages.error(request, str(exc))
    except Action.DoesNotExist as exc:
        raise Http404 from exc
    return redirect(f"/?workspace={membership.workspace_id}")


def service_identity(request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or len(header) > 120:
        return None
    return (
        ServiceKey.objects.filter(
            digest=hashlib.sha256(header[7:].encode()).hexdigest(), active=True
        )
        .select_related("workspace")
        .first()
    )


def serialized(action):
    return {
        "id": str(action.pk),
        "status": action.status,
        "reason": action.reason,
        "operation": action.operation,
        "destination": action.destination,
        "arguments_digest": action.arguments_digest,
        "cost_cents": action.cost_cents,
    }


# Only explicit Bearer service credentials work here. Cookies are never sufficient.
@csrf_exempt
@require_POST
def api_submit(request):
    identity = service_identity(request)
    if identity is None:
        return JsonResponse({"error": "Bearer service key required"}, status=401)
    try:
        action, created = submit(identity.workspace, f"service:{identity.pk}", json_body(request))
        return JsonResponse(serialized(action), status=201 if created else 200)
    except ValidationError as exc:
        return error_response(exc)


@csrf_exempt
def api_action(request, action_id, command=""):
    identity = service_identity(request)
    if identity is None:
        return JsonResponse({"error": "Bearer service key required"}, status=401)
    requester = f"service:{identity.pk}"
    try:
        action = Action.objects.get(pk=action_id, workspace=identity.workspace, requester=requester)
        if not command and request.method == "GET":
            return JsonResponse(serialized(action))
        if request.method != "POST":
            return JsonResponse({"error": "Method not allowed"}, status=405)
        if command == "lease":
            return JsonResponse({"lease_token": lease(identity.workspace, requester, action.pk)})
        if command == "complete":
            return JsonResponse(
                serialized(complete(identity.workspace, requester, action.pk, json_body(request)))
            )
        raise Http404
    except Action.DoesNotExist as exc:
        raise Http404 from exc
    except ValidationError as exc:
        return error_response(exc)
