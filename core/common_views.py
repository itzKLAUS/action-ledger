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
        response = JsonResponse(
            {
                "verification": verification,
                "events": list(
                    events.values(
                        "sequence", "kind", "actor", "payload", "previous", "digest", "created_at"
                    )
                ),
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
