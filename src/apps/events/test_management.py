from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import OrganizerProfile

from .models import Event, TicketCategory


User = get_user_model()


class OrganizerEventManagementTests(TestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(
            email="approved@example.com",
            password="StrongPassword123!",
        )

        OrganizerProfile.objects.create(
            user=self.organizer,
            organization_name="TUES",
            reason="Approved organizer test account.",
            status=OrganizerProfile.Status.APPROVED,
        )

        self.unapproved_user = User.objects.create_user(
            email="normal@example.com",
            password="StrongPassword123!",
        )

        self.client.force_login(self.organizer)

    def create_event(
        self,
        *,
        organizer=None,
        status=Event.Status.DRAFT,
        slug="managed-event",
    ):
        now = timezone.now()

        return Event.objects.create(
            organizer=organizer or self.organizer,
            name="Managed Event",
            slug=slug,
            starts_at=now + timedelta(days=10),
            ends_at=now + timedelta(days=11),
            registration_opens_at=now + timedelta(days=1),
            registration_closes_at=now + timedelta(days=9),
            status=status,
        )

    def event_form_data(self):
        now = timezone.now()

        starts_at = now + timedelta(days=10)
        ends_at = now + timedelta(days=11)
        registration_opens_at = now + timedelta(days=1)
        registration_closes_at = now + timedelta(days=9)

        def formatted(moment):
            return moment.strftime("%Y-%m-%d %H:%M")

        return {
            "name": "Organizer Event",
            "description": (
                "Created by an approved organizer."
            ),
            "venue": "TUES",

            "starts_at": formatted(starts_at),
            "ends_at": formatted(ends_at),

            "registration_opens_at": formatted(
                registration_opens_at
            ),
            "registration_closes_at": formatted(
                registration_closes_at
            ),

            "categories-TOTAL_FORMS": "1",
            "categories-INITIAL_FORMS": "0",
            "categories-MIN_NUM_FORMS": "0",
            "categories-MAX_NUM_FORMS": "1000",

            "categories-0-name": "Participant",
            "categories-0-description": (
                "Participant ticket."
            ),
            "categories-0-capacity": "100",
            "categories-0-per_user_limit": "1",

            "categories-0-registration_opens_at": "",
            "categories-0-registration_closes_at": "",

            "categories-0-is_active": "on",
            "categories-0-sort_order": "0",
        }

    def test_approved_organizer_can_open_dashboard(self):
        response = self.client.get(
            reverse("events_manage:list")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manage events")

    def test_unapproved_user_is_redirected(self):
        self.client.force_login(self.unapproved_user)

        response = self.client.get(
            reverse("events_manage:list")
        )

        self.assertRedirects(
            response,
            reverse("accounts:organizer_request"),
        )

    def test_approved_organizer_can_create_draft_event(self):
        response = self.client.post(
            reverse("events_manage:create"),
            self.event_form_data(),
        )

        self.assertRedirects(
            response,
            reverse("events_manage:list"),
        )

        event = Event.objects.get(
            slug="organizer-event"
        )

        self.assertEqual(
            event.organizer,
            self.organizer,
        )
        self.assertEqual(
            event.status,
            Event.Status.DRAFT,
        )

        self.assertTrue(
            TicketCategory.objects.filter(
                event=event,
                slug="participant",
            ).exists()
        )

    def test_organizer_cannot_edit_another_organizers_event(self):
        another_user = User.objects.create_user(
            email="other@example.com",
            password="StrongPassword123!",
        )

        event = self.create_event(
            organizer=another_user,
            slug="other-event",
        )

        response = self.client.get(
            reverse(
                "events_manage:edit",
                kwargs={"pk": event.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_organizer_can_delete_own_draft_event(self):
        event = self.create_event(
            status=Event.Status.DRAFT,
            slug="delete-draft",
        )

        response = self.client.post(
            reverse(
                "events_manage:delete",
                kwargs={"pk": event.pk},
            )
        )

        self.assertRedirects(
            response,
            reverse("events_manage:list"),
        )

        self.assertFalse(
            Event.objects.filter(pk=event.pk).exists()
        )

    def test_published_event_cannot_be_deleted(self):
        event = self.create_event(
            status=Event.Status.PUBLISHED,
            slug="published-delete-test",
        )

        response = self.client.post(
            reverse(
                "events_manage:delete",
                kwargs={"pk": event.pk},
            )
        )

        self.assertRedirects(
            response,
            reverse("events_manage:list"),
        )

        self.assertTrue(
            Event.objects.filter(pk=event.pk).exists()
        )

    def test_organizer_can_cancel_published_event(self):
        event = self.create_event(
            status=Event.Status.PUBLISHED,
            slug="cancel-published",
        )

        response = self.client.post(
            reverse(
                "events_manage:cancel",
                kwargs={"pk": event.pk},
            )
        )

        self.assertRedirects(
            response,
            reverse("events_manage:list"),
        )

        event.refresh_from_db()

        self.assertEqual(
            event.status,
            Event.Status.CANCELLED,
        )

    def test_organizer_cannot_cancel_another_organizers_event(self):
        another_user = User.objects.create_user(
            email="second-organizer@example.com",
            password="StrongPassword123!",
        )

        event = self.create_event(
            organizer=another_user,
            status=Event.Status.PUBLISHED,
            slug="other-cancelled-event",
        )

        response = self.client.post(
            reverse(
                "events_manage:cancel",
                kwargs={"pk": event.pk},
            )
        )

        self.assertEqual(response.status_code, 404)
