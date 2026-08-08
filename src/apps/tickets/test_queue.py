from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.events.models import Event, TicketCategory

from .models import Ticket, TicketRequest
from .queueing import (
    enqueue_ticket_request,
    process_next_ticket_request,
    ticket_request_queue_position,
)

User = get_user_model()


class TicketQueueTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.event = Event.objects.create(
            name="Queued Event",
            slug="queued-event",
            starts_at=self.now + timedelta(days=2),
            ends_at=self.now + timedelta(days=3),
            registration_opens_at=self.now - timedelta(hours=1),
            registration_closes_at=self.now + timedelta(days=1),
            status=Event.Status.PUBLISHED,
        )
        self.category = TicketCategory.objects.create(
            event=self.event,
            name="Participant",
            slug="participant",
            capacity=2,
            per_user_limit=1,
        )
        self.users = [self.create_user(number) for number in range(3)]

    def create_user(self, number):
        user = User.objects.create_user(
            email=f"queue-user-{number}@example.com",
        )
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=True,
        )
        return user

    def enqueue(self, user, key=None):
        with patch("apps.tickets.queueing._enqueue_task"):
            with self.captureOnCommitCallbacks(execute=True):
                return enqueue_ticket_request(
                    user=user,
                    category_id=self.category.pk,
                    idempotency_key=key or uuid4(),
                    moment=self.now,
                )

    def test_request_is_durable_before_worker_processes_it(self):
        result = self.enqueue(self.users[0])

        self.assertTrue(result.created)
        self.assertEqual(
            result.ticket_request.status,
            TicketRequest.Status.PENDING,
        )
        self.assertFalse(Ticket.objects.exists())

    def test_oldest_request_is_processed_first_without_overselling(self):
        self.category.capacity = 1
        self.category.save(update_fields=("capacity",))
        first = self.enqueue(self.users[0]).ticket_request
        second = self.enqueue(self.users[1]).ticket_request

        self.assertLess(first.id, second.id)
        self.assertEqual(ticket_request_queue_position(first), 1)
        self.assertEqual(ticket_request_queue_position(second), 2)

        processed_first = process_next_ticket_request(self.category.pk)
        processed_second = process_next_ticket_request(self.category.pk)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(processed_first.pk, first.pk)
        self.assertEqual(processed_second.pk, second.pk)
        self.assertEqual(first.status, TicketRequest.Status.SUCCEEDED)
        self.assertEqual(second.status, TicketRequest.Status.REJECTED)
        self.assertEqual(second.failure_code, "TicketSoldOutError")
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(Ticket.objects.get().user, self.users[0])

    def test_same_idempotency_key_reuses_request(self):
        key = uuid4()
        first = self.enqueue(self.users[0], key=key)
        replay = self.enqueue(self.users[0], key=key)

        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(
            replay.ticket_request.pk,
            first.ticket_request.pk,
        )
        self.assertEqual(TicketRequest.objects.count(), 1)

    def test_unexpected_worker_error_leaves_request_pending(self):
        ticket_request = self.enqueue(self.users[0]).ticket_request

        with (
            patch(
                "apps.tickets.queueing.issue_ticket",
                side_effect=RuntimeError("temporary failure"),
            ),
            self.assertRaises(RuntimeError),
        ):
            process_next_ticket_request(self.category.pk)

        ticket_request.refresh_from_db()
        self.assertEqual(
            ticket_request.status,
            TicketRequest.Status.PENDING,
        )
        self.assertFalse(Ticket.objects.exists())
