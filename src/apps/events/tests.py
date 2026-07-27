from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

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
