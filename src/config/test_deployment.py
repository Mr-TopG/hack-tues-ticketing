import os
from unittest.mock import patch

from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from . import views


class HealthViewTests(TestCase):
    def test_health_reports_database_readiness_without_caching(self):
        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "database": "ok",
            },
        )
        self.assertEqual(
            response["Cache-Control"],
            "max-age=0, no-cache, no-store, must-revalidate, private",
        )

    @patch.object(
        views.connection,
        "cursor",
        side_effect=DatabaseError,
    )
    def test_health_reports_database_failure(self, _cursor):
        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "status": "unavailable",
                "database": "unavailable",
            },
        )

    def test_health_rejects_mutating_methods(self):
        response = self.client.post(reverse("health"))

        self.assertEqual(response.status_code, 405)


class PublicPolicyPageTests(TestCase):
    def test_privacy_policy_is_public_and_describes_google_data(self):
        response = self.client.get(
            reverse("privacy_policy")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Privacy Policy")
        self.assertContains(response, "Google account")
        self.assertContains(response, "identifier, verified email address")
        self.assertContains(response, "do not sell personal information")

    def test_terms_are_public_and_cover_ticket_use(self):
        response = self.client.get(
            reverse("terms_of_service")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Terms of Service")
        self.assertContains(response, "Keep your ticket and QR code private")
        self.assertContains(
            response,
            reverse("privacy_policy"),
        )

    def test_site_footer_links_to_both_policy_pages(self):
        response = self.client.get(reverse("home"))

        self.assertContains(
            response,
            reverse("privacy_policy"),
        )
        self.assertContains(
            response,
            reverse("terms_of_service"),
        )


class GunicornConfigurationTests(SimpleTestCase):
    def test_production_server_uses_asgi_workers_and_safe_logs(self):
        config_path = (
            os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            + "/deploy/gunicorn.conf.py"
        )

        with open(config_path, encoding="utf-8") as config_file:
            config_source = config_file.read()

        self.assertIn(
            'worker_class = "uvicorn_worker.UvicornWorker"',
            config_source,
        )
        self.assertIn('worker_tmp_dir = "/dev/shm"', config_source)
        self.assertNotIn("%(r)s", config_source)
        self.assertNotIn("%(U)s", config_source)
        self.assertNotIn("%(q)s", config_source)


class NginxConfigurationTests(SimpleTestCase):
    def test_proxy_preserves_cloudflare_https_and_redacts_check_in_tokens(
        self,
    ):
        config_path = (
            os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            + "/deploy/nginx/ticketing.conf"
        )

        with open(config_path, encoding="utf-8") as config_file:
            config_source = config_file.read()

        self.assertIn(
            "map $http_x_forwarded_proto $origin_forwarded_proto",
            config_source,
        )
        self.assertIn(
            "proxy_set_header X-Forwarded-Proto "
            "$origin_forwarded_proto;",
            config_source,
        )
        self.assertIn(
            "/tickets/check-in/v1/[redacted]/",
            config_source,
        )
