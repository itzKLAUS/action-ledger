from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .common import member, verify
from .models import AuditEvent


@login_required
@require_GET
@transaction.atomic
def audit(request):
    membership = member(request)
    events = AuditEvent.objects.filter(workspace=membership.workspace)
    verification = "valid" if verify(membership.workspace) else "INVALID"
    if request.GET.get("format") == "json":
        try:
            after = int(request.GET.get("after", "0"))
            limit = int(request.GET.get("limit", "100"))
            if not 0 <= after <= 2**63 - 1 or not 1 <= limit <= 1000:
                raise ValueError
        except ValueError:
            return JsonResponse({"error": "Use after >= 0 and limit from 1 to 1000"}, status=400)
        page = list(
            events.filter(sequence__gt=after).values(
                "sequence", "kind", "actor", "payload", "previous", "digest", "created_at"
            )[:limit]
        )
        response = JsonResponse(
            {
                "verification": verification,
                "events": page,
                "next_after": page[-1]["sequence"] if page else after,
                "has_more": events.filter(
                    sequence__gt=page[-1]["sequence"] if page else after
                ).exists(),
            }
        )
        response["Content-Disposition"] = 'attachment; filename="audit.json"'
        return response
    return render(
        request,
        "audit.html",
        {"events": events[:500], "verification": verification, "membership": membership},
    )


@require_GET
def health(request):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})
