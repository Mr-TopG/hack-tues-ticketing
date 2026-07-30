from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import OrganizerProfile
from apps.events.models import Event, TicketCategory

from .models import Ticket
from .services import (
    IdempotencyConflictError,
    TicketAlreadyCheckedInError,
    TicketAlreadyCheckedInForEntryError,
    TicketCancelledCheckInError,
    TicketSoldOutError,
    cancel_ticket,
    check_in_ticket,
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
        self.delivery_enqueue_patcher = patch(
            "apps.tickets.delivery._enqueue_delivery"
        )
        self.delivery_enqueue_patcher.start()
        self.addCleanup(self.delivery_enqueue_patcher.stop)
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


@skipUnless(
    connection.vendor == "postgresql",
    "Ticket check-in concurrency tests require PostgreSQL.",
)
class TicketCheckInConcurrencyTests(TransactionTestCase):
    barrier_timeout = 30

    def setUp(self):
        self.now = timezone.now()
        self.organizer = User.objects.create_user(
            email="concurrent-organizer@example.com",
        )
        OrganizerProfile.objects.create(
            user=self.organizer,
            organization_name="Concurrency Events",
            reason="Runs the concurrency test event.",
            status=OrganizerProfile.Status.APPROVED,
            reviewed_at=self.now,
        )
        self.ticket_holder = User.objects.create_user(
            email="concurrent-ticket-holder@example.com",
        )
        self.global_checker = User.objects.create_superuser(
            email="concurrent-global-checker@example.com",
        )
        self.event = Event.objects.create(
            organizer=self.organizer,
            name="Check-in Concurrency Test Event",
            slug="check-in-concurrency-test-event",
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
        self.ticket = Ticket.objects.create(
            user=self.ticket_holder,
            category=self.category,
            idempotency_key=uuid4(),
        )

    def test_concurrent_double_scan_checks_in_once_and_preserves_audit(self):
        worker_count = 8
        barrier = Barrier(worker_count)
        validation_token = self.ticket.validation_token
        checker_ids = [
            (
                self.organizer.pk
                if number % 2 == 0
                else self.global_checker.pk
            )
            for number in range(worker_count)
        ]
        scan_base_time = timezone.now()
        scan_times = [
            scan_base_time + timedelta(microseconds=number)
            for number in range(worker_count)
        ]

        def scan(checker_id, scan_time):
            close_old_connections()
            try:
                checker = User.objects.get(pk=checker_id)
                barrier.wait(timeout=self.barrier_timeout)

                try:
                    result = check_in_ticket(
                        user=checker,
                        validation_token=validation_token,
                        moment=scan_time,
                    )
                except TicketAlreadyCheckedInForEntryError:
                    return "already_checked_in", None, None

                return (
                    "checked_in",
                    result.ticket.checked_in_at,
                    result.ticket.checked_in_by_id,
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(scan, checker_id, scan_time)
                for checker_id, scan_time in zip(
                    checker_ids,
                    scan_times,
                    strict=True,
                )
            ]
            results = [
                future.result(timeout=self.barrier_timeout)
                for future in futures
            ]

        successful_results = [
            result
            for result in results
            if result[0] == "checked_in"
        ]

        self.assertEqual(len(successful_results), 1)
        self.assertEqual(
            sum(
                outcome == "already_checked_in"
                for outcome, _checked_in_at, _checked_in_by_id in results
            ),
            worker_count - 1,
        )

        (
            _outcome,
            successful_check_in_at,
            successful_checker_id,
        ) = successful_results[0]
        self.ticket.refresh_from_db()

        self.assertEqual(
            self.ticket.status,
            Ticket.Status.CHECKED_IN,
        )
        self.assertEqual(
            self.ticket.checked_in_at,
            successful_check_in_at,
        )
        self.assertEqual(
            self.ticket.checked_in_by_id,
            successful_checker_id,
        )
        self.assertIsNone(self.ticket.cancelled_at)

    def test_concurrent_cancellation_and_check_in_have_one_terminal_winner(
        self,
    ):
        barrier = Barrier(2)
        ticket_id = self.ticket.pk
        validation_token = self.ticket.validation_token
        ticket_holder_id = self.ticket_holder.pk
        organizer_id = self.organizer.pk
        cancellation_time = self.now + timedelta(seconds=1)
        check_in_time = self.now + timedelta(seconds=2)

        def cancel():
            close_old_connections()
            try:
                ticket_holder = User.objects.get(pk=ticket_holder_id)
                barrier.wait(timeout=self.barrier_timeout)

                try:
                    result = cancel_ticket(
                        user=ticket_holder,
                        ticket_id=ticket_id,
                        moment=cancellation_time,
                    )
                except TicketAlreadyCheckedInError:
                    return "already_checked_in"

                self.assertTrue(result.cancelled)
                return "cancelled"
            finally:
                close_old_connections()

        def check_in():
            close_old_connections()
            try:
                organizer = User.objects.get(pk=organizer_id)
                barrier.wait(timeout=self.barrier_timeout)

                try:
                    check_in_ticket(
                        user=organizer,
                        validation_token=validation_token,
                        moment=check_in_time,
                    )
                except TicketCancelledCheckInError:
                    return "already_cancelled"

                return "checked_in"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            cancel_future = executor.submit(cancel)
            check_in_future = executor.submit(check_in)
            outcomes = (
                cancel_future.result(timeout=self.barrier_timeout),
                check_in_future.result(timeout=self.barrier_timeout),
            )

        self.assertIn(
            outcomes,
            {
                ("cancelled", "already_cancelled"),
                ("already_checked_in", "checked_in"),
            },
        )

        self.ticket.refresh_from_db()

        if self.ticket.status == Ticket.Status.CANCELLED:
            self.assertEqual(
                self.ticket.cancelled_at,
                cancellation_time,
            )
            self.assertIsNone(self.ticket.checked_in_at)
            self.assertIsNone(self.ticket.checked_in_by_id)
        else:
            self.assertEqual(
                self.ticket.status,
                Ticket.Status.CHECKED_IN,
            )
            self.assertIsNone(self.ticket.cancelled_at)
            self.assertEqual(
                self.ticket.checked_in_at,
                check_in_time,
            )
            self.assertEqual(
                self.ticket.checked_in_by_id,
                self.organizer.pk,
            )
