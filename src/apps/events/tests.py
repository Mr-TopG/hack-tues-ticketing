from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.tickets.models import Ticket

from .models import Event, TicketCategory


class EventModelTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

        self.event = Event(
            name="Hack TUES 13",
            slug="hack-tues-13",
            venue="TUES",
            starts_at=self.now + timedelta(days=5),
            ends_at=self.now + timedelta(days=7),
            registration_opens_at=(
                self.now - timedelta(hours=1)
            ),
            registration_closes_at=(
                self.now + timedelta(days=2)
            ),
            status=Event.Status.PUBLISHED,
        )

    def test_string_representation(self):
        self.assertEqual(
            str(self.event),
            "Hack TUES 13",
        )

    def test_valid_event_passes_validation(self):
        self.event.full_clean()

    def test_event_end_must_be_after_start(self):
        self.event.ends_at = self.event.starts_at

        with self.assertRaises(ValidationError):
            self.event.full_clean()

    def test_registration_close_must_be_after_open(self):
        self.event.registration_closes_at = (
            self.event.registration_opens_at
        )

        with self.assertRaises(ValidationError):
            self.event.full_clean()

    def test_published_event_registration_is_open(self):
        self.assertTrue(
            self.event.registration_is_open_at(self.now)
        )

    def test_draft_event_registration_is_closed(self):
        self.event.status = Event.Status.DRAFT

        self.assertFalse(
            self.event.registration_is_open_at(self.now)
        )


class TicketCategoryModelTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

        self.event = Event.objects.create(
            name="Hack TUES 13",
            slug="hack-tues-13",
            starts_at=self.now + timedelta(days=5),
            ends_at=self.now + timedelta(days=7),
            registration_opens_at=(
                self.now - timedelta(hours=1)
            ),
            registration_closes_at=(
                self.now + timedelta(days=2)
            ),
            status=Event.Status.PUBLISHED,
        )

        self.category = TicketCategory(
            event=self.event,
            name="Participant",
            slug="participant",
            capacity=500,
            per_user_limit=1,
        )

    def test_string_representation(self):
        self.assertEqual(
            str(self.category),
            "Hack TUES 13 — Participant",
        )

    def test_category_uses_event_registration_window(self):
        self.assertEqual(
            self.category.effective_registration_opens_at,
            self.event.registration_opens_at,
        )

        self.assertEqual(
            self.category.effective_registration_closes_at,
            self.event.registration_closes_at,
        )

    def test_active_category_registration_is_open(self):
        self.assertTrue(
            self.category.registration_is_open_at(self.now)
        )

    def test_inactive_category_registration_is_closed(self):
        self.category.is_active = False

        self.assertFalse(
            self.category.registration_is_open_at(self.now)
        )

    def test_category_close_must_be_after_open(self):
        self.category.registration_opens_at = self.now
        self.category.registration_closes_at = self.now

        with self.assertRaises(ValidationError):
            self.category.full_clean()

    def test_category_slug_is_unique_per_event(self):
        TicketCategory.objects.create(
            event=self.event,
            name="Participant",
            slug="participant",
            capacity=500,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TicketCategory.objects.create(
                    event=self.event,
                    name="Another participant category",
                    slug="participant",
                    capacity=100,
                )



class PublicEventViewTests(TestCase):
    def setUp(self):
        now = timezone.now()

        self.published_event = Event.objects.create(
            name="Public Hackathon",
            slug="public-hackathon",
            description="A published public event.",
            venue="TUES",
            starts_at=now + timedelta(days=5),
            ends_at=now + timedelta(days=7),
            registration_opens_at=now - timedelta(hours=1),
            registration_closes_at=now + timedelta(days=2),
            status=Event.Status.PUBLISHED,
        )

        self.draft_event = Event.objects.create(
            name="Secret Draft Event",
            slug="secret-draft-event",
            starts_at=now + timedelta(days=10),
            ends_at=now + timedelta(days=11),
            registration_opens_at=now + timedelta(days=2),
            registration_closes_at=now + timedelta(days=8),
            status=Event.Status.DRAFT,
        )

        self.cancelled_event = Event.objects.create(
            name="Cancelled Public Event",
            slug="cancelled-public-event",
            starts_at=now + timedelta(days=5),
            ends_at=now + timedelta(days=6),
            registration_opens_at=now - timedelta(days=2),
            registration_closes_at=now + timedelta(days=2),
            status=Event.Status.CANCELLED,
        )

        self.active_category = TicketCategory.objects.create(
            event=self.published_event,
            name="Participant",
            slug="participant",
            capacity=500,
            per_user_limit=1,
            is_active=True,
        )

        self.inactive_category = TicketCategory.objects.create(
            event=self.published_event,
            name="Hidden Staff",
            slug="hidden-staff",
            capacity=20,
            per_user_limit=1,
            is_active=False,
        )

    def test_event_list_only_shows_public_events(self):
        response = self.client.get(reverse("events:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Public Hackathon")
        self.assertContains(response, "Cancelled Public Event")
        self.assertNotContains(response, "Secret Draft Event")

    def test_event_detail_shows_active_ticket_categories(self):
        response = self.client.get(
            reverse(
                "events:detail",
                kwargs={"slug": self.published_event.slug},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Participant")
        self.assertContains(response, "Capacity:")
        self.assertContains(response, "500")
        self.assertNotContains(response, "Hidden Staff")

    def test_draft_event_detail_returns_not_found(self):
        response = self.client.get(
            reverse(
                "events:detail",
                kwargs={"slug": self.draft_event.slug},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_open_registration_state_is_displayed(self):
        response = self.client.get(
            reverse(
                "events:detail",
                kwargs={"slug": self.published_event.slug},
            )
        )

        self.assertContains(response, "Open")
        self.assertContains(response, "Registration is open")

    def test_availability_endpoint_returns_current_active_inventory(self):
        holder = User.objects.create_user(
            email="availability-holder@example.com",
        )
        Ticket.objects.create(
            user=holder,
            category=self.active_category,
            idempotency_key="d2fa0217-f613-4540-b7f5-ae4d92a8363e",
        )

        response = self.client.get(
            reverse(
                "events:availability",
                kwargs={"slug": self.published_event.slug},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "public, no-cache, no-store")
        payload = response.json()
        self.assertEqual(payload["event_state"], "open")
        self.assertEqual(
            payload["categories"],
            [
                {
                    "id": self.active_category.pk,
                    "available": 499,
                    "capacity": 500,
                    "registration_state": "open",
                }
            ],
        )
