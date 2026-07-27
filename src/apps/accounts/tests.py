from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
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
class AccountManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="status@example.com",
            password="StrongTestPassword123!",
            first_name="Old",
            last_name="Name",
        )

        self.email_address = EmailAddress.objects.create(
            user=self.user,
            email=self.user.email,
            primary=True,
            verified=False,
        )

        self.client.force_login(self.user)

    def test_unverified_status_and_resend_button_are_visible(self):
        response = self.client.get(
            reverse("accounts:manage")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Not verified")
        self.assertContains(
            response,
            "Resend verification",
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

    def test_verified_status_is_visible_on_account_page(self):
        self.email_address.verified = True
        self.email_address.save(
            update_fields=["verified"]
        )

        response = self.client.get(
            reverse("accounts:manage")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Verified")
        self.assertNotContains(
            response,
            "Resend verification",
        )

    def test_profile_information_can_be_updated(self):
        response = self.client.post(
            reverse("accounts:manage"),
            {
                "first_name": "Alex",
                "last_name": "Updated",
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:manage"),
        )

        self.user.refresh_from_db()

        self.assertEqual(
            self.user.first_name,
            "Alex",
        )
        self.assertEqual(
            self.user.last_name,
            "Updated",
        )


    def test_secondary_email_can_be_deleted(self):
        secondary = EmailAddress.objects.create(
            user=self.user,
            email="secondary@example.com",
            primary=False,
            verified=True,
        )

        response = self.client.post(
            reverse("account_email"),
            {
                "email": secondary.email,
                "action_remove": "1",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            EmailAddress.objects.filter(
                pk=secondary.pk,
            ).exists()
        )

    def test_primary_email_cannot_be_deleted(self):
        response = self.client.post(
            reverse("account_email"),
            {
                "email": self.email_address.email,
                "action_remove": "1",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            EmailAddress.objects.filter(
                pk=self.email_address.pk,
                primary=True,
            ).exists()
        )


class AccountManagementAccessTests(TestCase):
    def test_account_page_requires_authentication(self):
        response = self.client.get(
            reverse("accounts:manage")
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(
                reverse("account_login")
            )
        )


class AccountDeletionTests(TestCase):
    password = "StrongDeletePassword123!"

    def setUp(self):
        self.user = User.objects.create_user(
            email="delete@example.com",
            password=self.password,
            first_name="Delete",
            last_name="Test",
        )

        self.email_address = EmailAddress.objects.create(
            user=self.user,
            email=self.user.email,
            primary=True,
            verified=True,
        )

        self.social_account = SocialAccount.objects.create(
            user=self.user,
            provider="google",
            uid="google-delete-test",
        )

    def login_through_allauth(self):
        response = self.client.post(
            reverse("account_login"),
            {
                "login": self.user.email,
                "password": self.password,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            "_auth_user_id",
            self.client.session,
        )

    def test_delete_page_requires_login(self):
        response = self.client.get(
            reverse("accounts:delete")
        )

        self.assertEqual(response.status_code, 302)

    def test_delete_page_is_available_to_authenticated_user(self):
        self.login_through_allauth()

        response = self.client.get(
            reverse("accounts:delete")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Permanently delete account",
        )
        self.assertContains(
            response,
            self.user.email,
        )

    def test_wrong_confirmation_email_does_not_delete_account(self):
        self.login_through_allauth()
        user_pk = self.user.pk

        response = self.client.post(
            reverse("accounts:delete"),
            {
                "confirmation_email": "wrong@example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "The email address does not match your account.",
        )
        self.assertTrue(
            User.objects.filter(pk=user_pk).exists()
        )

    def test_account_and_related_auth_data_are_deleted(self):
        self.login_through_allauth()

        user_pk = self.user.pk
        email_address_pk = self.email_address.pk
        social_account_pk = self.social_account.pk

        response = self.client.post(
            reverse("accounts:delete"),
            {
                "confirmation_email": self.user.email,
            },
        )

        self.assertRedirects(
            response,
            reverse("home"),
        )

        self.assertFalse(
            User.objects.filter(pk=user_pk).exists()
        )
        self.assertFalse(
            EmailAddress.objects.filter(
                pk=email_address_pk
            ).exists()
        )
        self.assertFalse(
            SocialAccount.objects.filter(
                pk=social_account_pk
            ).exists()
        )
        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
        )
