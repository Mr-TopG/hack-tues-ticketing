from datetime import timedelta
from uuid import uuid4

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class TicketCheckInMigrationTests(TransactionTestCase):
    migrate_from = [("tickets", "0001_initial")]
    migrate_to = [("tickets", "0002_ticket_check_in_fields")]
    migrate_latest = [("tickets", "0004_ticket_email_delivery")]

    def setUp(self):
        super().setUp()

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(
            self.migrate_from
        ).apps

        User = old_apps.get_model("accounts", "User")
        Event = old_apps.get_model("events", "Event")
        TicketCategory = old_apps.get_model(
            "events",
            "TicketCategory",
        )
        Ticket = old_apps.get_model("tickets", "Ticket")

        now = timezone.now()
        event = Event.objects.create(
            name="Migration Test Event",
            slug="migration-test-event",
            starts_at=now + timedelta(days=2),
            ends_at=now + timedelta(days=3),
            registration_opens_at=now - timedelta(hours=1),
            registration_closes_at=now + timedelta(days=1),
            status="published",
        )
        category = TicketCategory.objects.create(
            event=event,
            name="Participant",
            slug="participant",
            capacity=3,
            per_user_limit=1,
            is_active=True,
        )

        for number in range(3):
            user = User.objects.create(
                email=f"migration-ticket-holder-{number}@example.com",
                password="!",
            )
            Ticket.objects.create(
                user=user,
                category=category,
                idempotency_key=uuid4(),
                status="issued",
            )

        preserved_fields = (
            "pk",
            "user_id",
            "category_id",
            "idempotency_key",
            "status",
            "issued_at",
            "cancelled_at",
            "checked_in_at",
        )
        self.expected_tickets = {
            ticket["pk"]: ticket
            for ticket in Ticket.objects.values(*preserved_fields)
        }

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.new_apps = executor.loader.project_state(
            self.migrate_to
        ).apps

    def tearDown(self):
        try:
            MigrationExecutor(connection).migrate(
                self.migrate_latest
            )
        finally:
            super().tearDown()

    def test_existing_tickets_receive_distinct_url_safe_tokens(self):
        Ticket = self.new_apps.get_model("tickets", "Ticket")
        preserved_fields = (
            "pk",
            "user_id",
            "category_id",
            "idempotency_key",
            "status",
            "issued_at",
            "cancelled_at",
            "checked_in_at",
        )
        migrated_tickets = list(
            Ticket.objects.filter(
                pk__in=self.expected_tickets,
            ).values(
                *preserved_fields,
                "validation_token",
                "checked_in_by_id",
            )
        )

        self.assertEqual(
            Ticket.objects.count(),
            len(self.expected_tickets),
        )
        self.assertEqual(
            {ticket["pk"] for ticket in migrated_tickets},
            set(self.expected_tickets),
        )

        tokens = []

        for ticket in migrated_tickets:
            expected = self.expected_tickets[ticket["pk"]]

            for field in preserved_fields:
                self.assertEqual(ticket[field], expected[field])

            token = ticket["validation_token"]
            self.assertEqual(len(token), 43)
            self.assertRegex(token, r"\A[A-Za-z0-9_-]{43}\Z")
            self.assertIsNone(ticket["checked_in_by_id"])
            tokens.append(token)

        self.assertEqual(len(tokens), len(set(tokens)))
