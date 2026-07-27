from allauth.account.models import EmailAddress
from allauth.account.signals import email_confirmed
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class AllauthSignupTests(TestCase):
    def test_signup_creates_unverified_user_and_sends_email(self):
        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "NewUser@Example.com",
                "first_name": "Alex",
                "last_name": "Example",
                "password1": "StrongTestPassword123!",
                "password2": "StrongTestPassword123!",
            },
        )

        self.assertEqual(response.status_code, 302)

        user = User.objects.get(
            email="newuser@example.com",
        )

        self.assertEqual(user.first_name, "Alex")
        self.assertEqual(user.last_name, "Example")
        self.assertIsNone(user.email_verified_at)

        email_address = EmailAddress.objects.get(
            user=user,
            email=user.email,
        )

        self.assertFalse(email_address.verified)
        self.assertTrue(email_address.primary)

        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].to,
            ["newuser@example.com"],
        )


class VerificationSynchronizationTests(TestCase):
    def test_confirmation_records_verification_time(self):
        user = User.objects.create_user(
            email="verify@example.com",
            password="StrongTestPassword123!",
        )

        email_address = EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=True,
        )

        email_confirmed.send(
            sender=EmailAddress,
            request=None,
            email_address=email_address,
        )

        user.refresh_from_db()

        self.assertIsNotNone(user.email_verified_at)


class AllauthLoginTests(TestCase):
    def test_verified_user_can_log_in_by_email(self):
        user = User.objects.create_user(
            email="login@example.com",
            password="StrongTestPassword123!",
        )

        EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=True,
        )

        response = self.client.post(
            reverse("account_login"),
            {
                "login": user.email,
                "password": "StrongTestPassword123!",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            str(self.client.session["_auth_user_id"]),
            str(user.pk),
        )

        user.refresh_from_db()

        self.assertIsNotNone(user.email_verified_at)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class EmailVerificationStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="status@example.com",
            password="StrongTestPassword123!",
        )

        self.email_address = EmailAddress.objects.create(
            user=self.user,
            email=self.user.email,
            primary=True,
            verified=False,
        )

        self.client.force_login(self.user)

    def test_unverified_status_and_resend_button_are_visible(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email not verified")
        self.assertContains(
            response,
            "Resend verification email",
        )

    def test_resend_button_sends_confirmation_email(self):
        response = self.client.post(
            reverse("account_email"),
            {
                "email": self.user.email,
                "action_send": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].to,
            [self.user.email],
        )

    def test_verification_warning_is_hidden_after_verification(self):
        self.email_address.verified = True
        self.email_address.save(update_fields=["verified"])

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            "Email not verified",
        )
        self.assertNotContains(
            response,
            "Resend verification email",
        )
