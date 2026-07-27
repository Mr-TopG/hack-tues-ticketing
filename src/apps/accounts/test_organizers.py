from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import OrganizerProfile


User = get_user_model()


class OrganizerRequestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="organizer@example.com",
            password="StrongPassword123!",
        )

    def test_request_page_requires_login(self):
        response = self.client.get(
            reverse("accounts:organizer_request")
        )

        self.assertEqual(response.status_code, 302)

    def test_user_can_request_organizer_access(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:organizer_request"),
            {
                "organization_name": "TUES",
                "reason": (
                    "I need to create and manage our school "
                    "hackathon events."
                ),
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:organizer_request"),
        )

        profile = OrganizerProfile.objects.get(
            user=self.user
        )

        self.assertEqual(
            profile.status,
            OrganizerProfile.Status.PENDING,
        )

    def test_rejected_request_can_be_resubmitted(self):
        profile = OrganizerProfile.objects.create(
            user=self.user,
            organization_name="Old organization",
            reason="This is an old rejected organizer request.",
            status=OrganizerProfile.Status.REJECTED,
        )

        self.client.force_login(self.user)

        self.client.post(
            reverse("accounts:organizer_request"),
            {
                "organization_name": "TUES",
                "reason": (
                    "This is a new and updated organizer "
                    "request for the school."
                ),
            },
        )

        profile.refresh_from_db()

        self.assertEqual(
            profile.status,
            OrganizerProfile.Status.PENDING,
        )
        self.assertIsNone(profile.reviewed_at)
        self.assertIsNone(profile.reviewed_by)
