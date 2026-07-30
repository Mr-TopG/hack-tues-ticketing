from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless
from uuid import uuid4

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from django.utils import timezone

from apps.events.models import Event, TicketCategory

from .models import Ticket
from .services import (
    IdempotencyConflictError,
    TicketSoldOutError,
    issue_ticket,
)


User = get_user_model()


@skipUnless(
    connection.vendor == "postgresql",
    "Ticket allocation concurrency tests require PostgreSQL.",
)
class TicketAllocationConcurrencyTests(TransactionTestCase):
    barrier_timeout = 30

    def setUp(self):
        self.now = timezone.now()
        self.event = Event.objects.create(
            name="Concurrency Test Event",
            slug="concurrency-test-event",
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
            capacity=5,
            per_user_limit=1,
            is_active=True,
        )

    def create_verified_user(self, number):
        user = User.objects.create_user(
            email=f"concurrent-user-{number}@example.com",
        )
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=True,
        )
        return user

    def test_capacity_five_allows_exactly_five_of_twenty_attempts(self):
        users = [
            self.create_verified_user(number)
            for number in range(20)
        ]
        attempts = [
            (user.pk, uuid4())
            for user in users
        ]
        barrier = Barrier(len(attempts))
        category_id = self.category.pk
        request_time = self.now

        def allocate(user_id, idempotency_key):
            close_old_connections()
            try:
                user = User.objects.get(pk=user_id)
                barrier.wait(timeout=self.barrier_timeout)

                try:
                    result = issue_ticket(
                        user=user,
                        category_id=category_id,
                        idempotency_key=idempotency_key,
                        moment=request_time,
                    )
                except TicketSoldOutError:
                    return "sold_out", None

                return (
                    "created" if result.created else "existing",
                    result.ticket.pk,
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(attempts)) as executor:
            futures = [
                executor.submit(allocate, user_id, key)
                for user_id, key in attempts
            ]
            results = [
                future.result(timeout=self.barrier_timeout)
                for future in futures
            ]

        created = [
            ticket_id
            for outcome, ticket_id in results
            if outcome == "created"
        ]
        sold_out = [
            outcome
            for outcome, _ticket_id in results
            if outcome == "sold_out"
        ]

        self.assertEqual(
            {outcome for outcome, _ticket_id in results},
            {"created", "sold_out"},
        )
        self.assertEqual(len(created), 5)
        self.assertEqual(len(set(created)), 5)
        self.assertEqual(len(sold_out), 15)
        self.assertEqual(
            Ticket.objects.filter(category=self.category).count(),
            5,
        )
        self.assertEqual(
            Ticket.objects.filter(
                category=self.category,
                status__in=Ticket.ACTIVE_STATUSES,
            ).count(),
            5,
        )

    def test_same_idempotency_key_concurrently_creates_one_ticket(self):
        user = self.create_verified_user("idempotent")
        worker_count = 10
        barrier = Barrier(worker_count)
        category_id = self.category.pk
        user_id = user.pk
        idempotency_key = uuid4()
        request_time = self.now

        def allocate():
            close_old_connections()
            try:
                worker_user = User.objects.get(pk=user_id)
                barrier.wait(timeout=self.barrier_timeout)
                result = issue_ticket(
                    user=worker_user,
                    category_id=category_id,
                    idempotency_key=idempotency_key,
                    moment=request_time,
                )
                return result.created, result.ticket.pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(allocate)
                for _number in range(worker_count)
            ]
            results = [
                future.result(timeout=self.barrier_timeout)
                for future in futures
            ]

        ticket_ids = {ticket_id for _created, ticket_id in results}

        self.assertEqual(
            sum(created for created, _ticket_id in results),
            1,
        )
        self.assertEqual(len(ticket_ids), 1)
        self.assertEqual(
            Ticket.objects.filter(
                idempotency_key=idempotency_key,
            ).count(),
            1,
        )

    def test_cross_category_idempotency_reuse_has_one_winner(self):
        user = self.create_verified_user("conflict")
        other_category = TicketCategory.objects.create(
            event=self.event,
            name="Alternate participant",
            slug="alternate-participant",
            capacity=5,
            per_user_limit=1,
            is_active=True,
        )
        category_ids = (
            self.category.pk,
            other_category.pk,
        )
        barrier = Barrier(len(category_ids))
        user_id = user.pk
        idempotency_key = uuid4()
        request_time = self.now

        def allocate(category_id):
            close_old_connections()
            try:
                worker_user = User.objects.get(pk=user_id)
                barrier.wait(timeout=self.barrier_timeout)

                try:
                    result = issue_ticket(
                        user=worker_user,
                        category_id=category_id,
                        idempotency_key=idempotency_key,
                        moment=request_time,
                    )
                except IdempotencyConflictError:
                    return "conflict", None

                return (
                    "created" if result.created else "existing",
                    result.ticket.pk,
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(category_ids)) as executor:
            futures = [
                executor.submit(allocate, category_id)
                for category_id in category_ids
            ]
            results = [
                future.result(timeout=self.barrier_timeout)
                for future in futures
            ]

        self.assertCountEqual(
            [outcome for outcome, _ticket_id in results],
            ["created", "conflict"],
        )
        self.assertEqual(
            Ticket.objects.filter(
                idempotency_key=idempotency_key,
            ).count(),
            1,
        )
