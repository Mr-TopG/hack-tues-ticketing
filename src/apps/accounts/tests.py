from django.core import mail
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .services import create_verification_token


User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    APP_BASE_URL="http://testserver",
)
class RegistrationTests(TestCase):
    def test_registration_creates_user_and_sends_email(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": "NewUser@Example.com",
                "first_name": "Alex",
                "last_name": "Example",
                "password1": "StrongTestPassword123!",
                "password2": "StrongTestPassword123!",
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:verification-sent"),
        )

        user = User.objects.get(
            email="newuser@example.com",
        )

        self.assertEqual(user.first_name, "Alex")
        self.assertIsNone(user.email_verified_at)

        self.assertEqual(
            str(self.client.session["_auth_user_id"]),
            str(user.pk),
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].to,
            ["newuser@example.com"],
        )
        self.assertIn(
            "/accounts/verify/",
            mail.outbox[0].body,
        )

    def test_email_is_case_insensitively_unique(self):
        User.objects.create_user(
            email="person@example.com",
            password="StrongTestPassword123!",
        )

        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": "PERSON@EXAMPLE.COM",
                "first_name": "Another",
                "last_name": "Person",
                "password1": "StrongTestPassword123!",
                "password2": "StrongTestPassword123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "already exists",
        )


class EmailVerificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="verify@example.com",
            password="StrongTestPassword123!",
        )

    def test_valid_token_verifies_email(self):
        token = create_verification_token(self.user)

        response = self.client.get(
            reverse(
                "accounts:verify-email",
                kwargs={"token": token},
            )
        )

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()

        self.assertIsNotNone(
            self.user.email_verified_at,
        )

    def test_invalid_token_is_rejected(self):
        response = self.client.get(
            reverse(
                "accounts:verify-email",
                kwargs={"token": "invalid-token"},
            )
        )

        self.assertEqual(response.status_code, 400)


class LoginTests(TestCase):
    def test_user_can_log_in_with_email(self):
        User.objects.create_user(
            email="login@example.com",
            password="StrongTestPassword123!",
        )

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "login@example.com",
                "password": "StrongTestPassword123!",
            },
        )

        self.assertRedirects(
            response,
            reverse("home"),
        )
