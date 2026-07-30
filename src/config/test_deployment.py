import os
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
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


class UserInterfaceShellTests(TestCase):
    def test_homepage_includes_theme_and_mobile_navigation_controls(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, "data-theme-toggle")
        self.assertContains(response, 'class="nav-menu"')
        self.assertContains(response, 'class="nav-primary"')
        self.assertContains(response, 'class="nav-utility"')
        self.assertContains(response, "/static/js/theme.js")
        self.assertContains(response, "/static/css/app.css")

        content = response.content.decode()
        navigation = content[
            content.index('<div class="nav-actions">'):
            content.index("</details>")
        ]
        self.assertLess(
            navigation.index("Register"),
            navigation.index("data-theme-toggle"),
        )

    def test_public_pages_share_the_global_theme_stylesheet(self):
        page_names = (
            "home",
            "events:list",
            "account_login",
            "account_signup",
            "privacy_policy",
            "terms_of_service",
        )

        for page_name in page_names:
            with self.subTest(page_name=page_name):
                response = self.client.get(reverse(page_name))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "/static/css/app.css")
                self.assertContains(response, "data-theme-toggle")

    def test_stylesheet_contains_dark_theme_and_phone_breakpoint(self):
        stylesheet = (
            Path(settings.BASE_DIR) / "static" / "css" / "app.css"
        ).read_text(encoding="utf-8")

        self.assertIn('[data-theme="dark"]', stylesheet)
        self.assertIn("@media (max-width: 1000px)", stylesheet)
        self.assertIn("@media (max-width: 700px)", stylesheet)
        self.assertIn("min-height: 44px", stylesheet)
        self.assertIn("overflow-x: hidden", stylesheet)
        self.assertIn("--dominant-page:", stylesheet)
        self.assertIn("--secondary-surface:", stylesheet)
        self.assertIn("--accent-color:", stylesheet)
        self.assertIn("--dominant-page: #e8edf4", stylesheet)
        self.assertIn("--dominant-page: #050a13", stylesheet)
        self.assertIn("--accent-action:", stylesheet)
        self.assertIn(
            "background: var(--secondary-surface)",
            stylesheet,
        )
        self.assertIn("background: #001a38", stylesheet)

    def test_theme_script_persists_preference_and_syncs_mobile_menu(self):
        script = (
            Path(settings.BASE_DIR) / "static" / "js" / "theme.js"
        ).read_text(encoding="utf-8")

        self.assertIn('localStorage.setItem("ticketing-theme"', script)
        self.assertIn('matchMedia("(max-width: 1000px)")', script)

    def test_authenticated_header_does_not_display_email_address(self):
        user = get_user_model().objects.create_user(
            email="private-header@example.com",
            password="StrongTestPassword123!",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertNotContains(response, user.email)
        self.assertContains(response, reverse("accounts:manage"))

        content = response.content.decode()
        navigation = content[
            content.index('<div class="nav-actions">'):
            content.index("</details>")
        ]
        self.assertLess(
            navigation.index("Events"),
            navigation.index("My tickets"),
        )
        self.assertLess(
            navigation.index("My tickets"),
            navigation.index("Account"),
        )
        self.assertLess(
            navigation.index("Account"),
            navigation.index("data-theme-toggle"),
        )
        self.assertLess(
            navigation.index("Log out"),
            navigation.index("data-theme-toggle"),
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


class EmailConfigurationTests(SimpleTestCase):
    def test_cloudflare_smtp_example_uses_implicit_tls(self):
        example_path = Path(settings.PROJECT_ROOT) / ".env.example"
        example = example_path.read_text(encoding="utf-8")

        self.assertIn("EMAIL_HOST=smtp.mx.cloudflare.net", example)
        self.assertIn("EMAIL_PORT=465", example)
        self.assertIn("EMAIL_HOST_USER=api_token", example)
        self.assertIn("EMAIL_USE_TLS=false", example)
        self.assertIn("EMAIL_USE_SSL=true", example)

    def test_free_smtp_examples_use_starttls(self):
        example_path = Path(settings.PROJECT_ROOT) / ".env.example"
        example = example_path.read_text(encoding="utf-8")

        self.assertIn("EMAIL_HOST=smtp-relay.brevo.com", example)
        self.assertIn("EMAIL_HOST=smtp.resend.com", example)
        self.assertIn("EMAIL_HOST_USER=resend", example)
        self.assertIn("EMAIL_PORT=587", example)

    def test_settings_reject_conflicting_email_encryption_modes(self):
        settings_source = (
            Path(settings.BASE_DIR) / "config" / "settings.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "if EMAIL_USE_TLS and EMAIL_USE_SSL:",
            settings_source,
        )
        self.assertIn(
            "EMAIL_HOST_USER and EMAIL_HOST_PASSWORD must be configured",
            settings_source,
        )


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
            "resolver 127.0.0.11",
            config_source,
        )
        self.assertIn(
            "server web:8000 resolve;",
            config_source,
        )
        self.assertIn(
            "/tickets/check-in/v1/[redacted]/",
            config_source,
        )
