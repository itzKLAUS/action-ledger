import hmac
import time

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse

from .models import LoginBucket


class LoginThrottleMiddleware:
    """Shared fixed-window counters; raw usernames and IP addresses are not stored."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/login/" and request.method == "POST":
            window = int(time.time()) // 900
            username = request.POST.get("username", "")[:150].casefold()
            ip = request.META.get("REMOTE_ADDR", "unknown")
            with transaction.atomic():
                for identity, limit in [("ip:" + ip, 250), ("user:" + username, 10)]:
                    key = hmac.new(
                        settings.SECRET_KEY.encode(), identity.encode(), "sha256"
                    ).hexdigest()
                    bucket, _ = LoginBucket.objects.get_or_create(key=key, window=window)
                    bucket = LoginBucket.objects.select_for_update().get(pk=bucket.pk)
                    if bucket.count >= limit:
                        response = HttpResponse(
                            "Too many sign-in attempts. Try again later.", status=429
                        )
                        response["Retry-After"] = str(900 - int(time.time()) % 900)
                        return response
                    bucket.count += 1
                    bucket.save(update_fields=["count"])
        return self.get_response(request)


class SecurityHeadersMiddleware:
    """No third-party scripts or remote browser connections; dynamic responses are private."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
        )
        response["Referrer-Policy"] = "same-origin"
        if not request.path.startswith("/static/"):
            response["Cache-Control"] = "private, no-store"
        return response
