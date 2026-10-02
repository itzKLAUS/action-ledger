from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from .models import LoginBucket


@override_settings(
    SECURE_SSL_REDIRECT=False,
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
)
class SecurityTests(TestCase):
    def test_login_throttle_is_shared_and_expires(self):
        with patch("core.security.time.time", return_value=90000):
            for _ in range(10):
                response = Client().post("/login/", {"username": "synthetic", "password": "fake"})
                self.assertEqual(response.status_code, 200)
            response = Client().post("/login/", {"username": "synthetic", "password": "fake"})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response["Retry-After"], "900")
        with patch("core.security.time.time", return_value=90900):
            self.assertEqual(
                Client().post("/login/", {"username": "synthetic", "password": "fake"}).status_code,
                200,
            )
        self.assertFalse(LoginBucket.objects.filter(key__contains="synthetic").exists())

    def test_dynamic_responses_have_privacy_headers(self):
        response = self.client.get("/health/")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
