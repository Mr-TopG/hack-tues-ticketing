from datetime import timedelta
from secrets import token_urlsafe
from unittest.mock import patch
from uuid import UUID, uuid4

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.db import IntegrityError, transaction
from django.db.models.deletion import PROTECT, ProtectedError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import OrganizerProfile
from apps.events.models import Event, TicketCategory

from .models import Ticket, TicketEmailDelivery
from .services import (
    AuthenticationRequiredError,
    EmailNotVerifiedError,
    EventCheckInUnavailableError,
    IdempotencyConflictError,
    InactiveTicketCategoryError,
    InvalidIdempotencyKeyError,
    PerUserLimitReachedError,
    RegistrationClosedError,
    TicketAlreadyCheckedInError,
    TicketAlreadyCheckedInForEntryError,
    TicketCancellationClosedError,
    TicketCancelledCheckInError,
    TicketNotFoundError,
    TicketSoldOutError,
    cancel_ticket,
    check_in_ticket,
    issue_ticket,
)

User = get_user_model()


class TicketFixtureMixin:
    def setUp(self):
        super().setUp()

        self.now = timezone.now().replace(microsecond=0)
        self.event = Event.objects.create(
            name="Hack TUES Ticket Tests",
            starts_at=self.now + timedelta(days=5),
            ends_at=self.now + timedelta(days=6),
            registration_opens_at=self.now - timedelta(days=1),
            registration_closes_at=self.now + timedelta(days=2),
            status=Event.Status.PUBLISHED,
        )
        self.category = TicketCategory.objects.create(
            event=self.event,
            name="Participant",
            capacity=2,
            per_user_limit=1,
        )
        self.user = self.create_user(
            "ticket-holder@example.com",
            verified=True,
        )

    def create_user(
        self,
        email,
        *,
        verified,
        email_verified_at=None,
    ):
        user = User.objects.create_user(
            email=email,
            password="StrongTestPassword123!",
            email_verified_at=email_verified_at,
        )
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=verified,
        )
        return user

    def create_category(self, **overrides):
        values = {
            "event": self.event,
            "name": f"Category {uuid4().hex[:8]}",
            "capacity": 2,
            "per_user_limit": 1,
        }
        values.update(overrides)
        return TicketCategory.objects.create(**values)

    def create_ticket(self, **overrides):
        values = {
            "user": self.user,
            "category": self.category,
            "idempotency_key": uuid4(),
        }
        values.update(overrides)
        return Ticket.objects.create(**values)

    def issue(
        self,
        *,
        user=None,
        category=None,
        key=None,
        moment=None,
    ):
        return issue_ticket(
            user=user or self.user,
            category_id=(category or self.category).pk,
            idempotency_key=key or uuid4(),
            moment=moment or self.now,
        )


class TicketModelTests(TicketFixtureMixin, TestCase):
    def test_schema_defaults_to_issued_ticket_with_uuid_identifiers(self):
        key = uuid4()

        ticket = Ticket.objects.create(
            user=self.user,
            category=self.category,
            idempotency_key=key,
        )

        self.assertIsInstance(ticket.pk, UUID)
        self.assertEqual(ticket.idempotency_key, key)
        self.assertEqual(ticket.status, Ticket.Status.ISSUED)
        self.assertIsNotNone(ticket.issued_at)
        self.assertIsNone(ticket.cancelled_at)
        self.assertIsNone(ticket.checked_in_at)
        self.assertIsNone(ticket.checked_in_by)

        id_field = Ticket._meta.get_field("id")
        idempotency_field = Ticket._meta.get_field("idempotency_key")
        validation_token_field = Ticket._meta.get_field(
            "validation_token"
        )
        checked_in_by_field = Ticket._meta.get_field(
            "checked_in_by"
        )

        self.assertTrue(id_field.primary_key)
        self.assertFalse(id_field.editable)
        self.assertTrue(idempotency_field.unique)
        self.assertFalse(idempotency_field.editable)
        self.assertEqual(validation_token_field.max_length, 43)
        self.assertTrue(validation_token_field.unique)
        self.assertFalse(validation_token_field.editable)
        self.assertTrue(checked_in_by_field.null)
        self.assertTrue(checked_in_by_field.blank)
        self.assertIs(
            checked_in_by_field.remote_field.on_delete,
            PROTECT,
        )

    def test_validation_tokens_are_unique_and_url_safe(self):
        tickets = [
            self.create_ticket()
            for _number in range(10)
        ]
        tokens = {
            ticket.validation_token
            for ticket in tickets
        }

        self.assertEqual(len(tokens), len(tickets))

        for ticket in tickets:
            with self.subTest(ticket=ticket.pk):
                self.assertRegex(
                    ticket.validation_token,
                    r"\A[A-Za-z0-9_-]{43}\Z",
                )
                self.assertNotEqual(
                    ticket.validation_token,
                    str(ticket.pk),
                )
                self.assertNotEqual(
                    ticket.validation_token,
                    str(ticket.idempotency_key),
                )

    def test_database_rejects_duplicate_validation_token(self):
        token = token_urlsafe(32)
        self.create_ticket(validation_token=token)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_ticket(validation_token=token)

    def test_active_statuses_count_against_capacity(self):
        ticket = self.create_ticket()

        self.assertTrue(ticket.counts_against_capacity)

        ticket.status = Ticket.Status.CHECKED_IN
        self.assertTrue(ticket.counts_against_capacity)

        ticket.status = Ticket.Status.CANCELLED
        self.assertFalse(ticket.counts_against_capacity)

    def test_database_rejects_inconsistent_status_timestamps(self):
        invalid_states = (
            {
                "status": Ticket.Status.ISSUED,
                "cancelled_at": self.now,
            },
            {
                "status": Ticket.Status.CANCELLED,
            },
            {
                "status": Ticket.Status.CHECKED_IN,
            },
            {
                "status": Ticket.Status.ISSUED,
                "checked_in_by": self.user,
            },
            {
                "status": Ticket.Status.CANCELLED,
                "cancelled_at": self.now,
                "checked_in_by": self.user,
            },
            {
                "status": Ticket.Status.CHECKED_IN,
                "checked_in_at": self.now,
            },
            {
                "status": Ticket.Status.CHECKED_IN,
                "checked_in_by": self.user,
            },
            {
                "status": "unknown",
            },
        )

        for invalid_state in invalid_states:
            with (
                self.subTest(invalid_state=invalid_state),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                self.create_ticket(**invalid_state)

    def test_idempotency_key_is_unique(self):
        key = uuid4()
        self.create_ticket(idempotency_key=key)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_ticket(idempotency_key=key)

    def test_ticket_relationships_protect_history(self):
        ticket = self.create_ticket()

        with self.assertRaises(ProtectedError):
            self.user.delete()

        with self.assertRaises(ProtectedError):
            self.category.delete()

        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())

    def test_checked_in_by_relationship_protects_audit_history(self):
        checker = self.create_user(
            "audit-checker@example.com",
            verified=True,
        )
        ticket = self.create_ticket(
            status=Ticket.Status.CHECKED_IN,
            checked_in_at=self.now,
            checked_in_by=checker,
        )

        with self.assertRaises(ProtectedError) as error_context:
            checker.delete()

        self.assertIn(
            ticket,
            error_context.exception.protected_objects,
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.checked_in_by, checker)
        self.assertEqual(ticket.checked_in_at, self.now)

    def test_cancellation_availability_depends_on_status_and_event_start(self):
        ticket = self.create_ticket()

        self.assertTrue(ticket.can_be_cancelled_at(self.now))
        self.assertFalse(
            ticket.can_be_cancelled_at(self.event.starts_at)
        )

        ticket.status = Ticket.Status.CANCELLED

        self.assertFalse(ticket.can_be_cancelled_at(self.now))


class TicketIssueServiceTests(TicketFixtureMixin, TestCase):
    def test_issue_requires_authentication(self):
        with self.assertRaises(AuthenticationRequiredError):
            issue_ticket(
                user=AnonymousUser(),
                category_id=self.category.pk,
                idempotency_key=uuid4(),
                moment=self.now,
            )

        self.assertFalse(Ticket.objects.exists())

    def test_issue_rejects_invalid_idempotency_key(self):
        with self.assertRaises(InvalidIdempotencyKeyError):
            issue_ticket(
                user=self.user,
                category_id=self.category.pk,
                idempotency_key="not-a-uuid",
                moment=self.now,
            )

        self.assertFalse(Ticket.objects.exists())

    def test_successful_issue_returns_created_ticket(self):
        key = uuid4()

        result = self.issue(key=str(key))

        self.assertTrue(result.created)
        self.assertEqual(result.ticket.user, self.user)
        self.assertEqual(result.ticket.category, self.category)
        self.assertEqual(result.ticket.idempotency_key, key)
        self.assertEqual(result.ticket.status, Ticket.Status.ISSUED)
        self.assertTrue(result.ticket.counts_against_capacity)
        self.assertEqual(Ticket.objects.count(), 1)
        delivery = TicketEmailDelivery.objects.get(
            ticket=result.ticket
        )
        self.assertEqual(
            delivery.status,
            TicketEmailDelivery.Status.PENDING,
        )
        self.assertEqual(delivery.recipient, self.user.email)

    @patch("apps.tickets.delivery._enqueue_delivery")
    def test_successful_issue_enqueues_email_after_commit(
        self,
        enqueue,
    ):
        with self.captureOnCommitCallbacks(execute=True):
            result = self.issue()

        delivery = TicketEmailDelivery.objects.get(
            ticket=result.ticket
        )
        enqueue.assert_called_once_with(delivery.pk)

    def test_same_key_replay_returns_existing_ticket(self):
        self.category.capacity = 1
        self.category.save(update_fields=("capacity",))
        key = uuid4()

        first_result = self.issue(key=key)
        replay_result = self.issue(key=key)

        self.assertTrue(first_result.created)
        self.assertFalse(replay_result.created)
        self.assertEqual(replay_result.ticket.pk, first_result.ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketEmailDelivery.objects.count(), 1)

    def test_same_key_reuse_by_another_user_is_rejected(self):
        key = uuid4()
        self.issue(key=key)
        other_user = self.create_user(
            "other-holder@example.com",
            verified=True,
        )

        with self.assertRaises(IdempotencyConflictError):
            self.issue(user=other_user, key=key)

        self.assertEqual(Ticket.objects.count(), 1)

    def test_same_key_reuse_for_another_category_is_rejected(self):
        key = uuid4()
        self.issue(key=key)
        other_category = self.create_category()

        with self.assertRaises(IdempotencyConflictError):
            self.issue(category=other_category, key=key)

        self.assertEqual(Ticket.objects.count(), 1)

    def test_allauth_verification_is_required_even_with_legacy_timestamp(self):
        unverified_user = self.create_user(
            "legacy-verified@example.com",
            verified=False,
            email_verified_at=self.now,
        )

        with self.assertRaises(EmailNotVerifiedError):
            self.issue(user=unverified_user)

        self.assertFalse(
            Ticket.objects.filter(user=unverified_user).exists()
        )

    def test_allauth_verification_authorizes_without_legacy_timestamp(self):
        self.assertIsNone(self.user.email_verified_at)

        result = self.issue()

        self.assertTrue(result.created)

    def test_verified_record_for_another_email_does_not_authorize(self):
        user = self.create_user(
            "current-address@example.com",
            verified=False,
        )
        EmailAddress.objects.create(
            user=user,
            email="old-address@example.com",
            primary=False,
            verified=True,
        )

        with self.assertRaises(EmailNotVerifiedError):
            self.issue(user=user)

        self.assertFalse(Ticket.objects.filter(user=user).exists())

    def test_inactive_category_is_rejected(self):
        self.category.is_active = False
        self.category.save(update_fields=("is_active",))

        with self.assertRaises(InactiveTicketCategoryError):
            self.issue()

        self.assertFalse(Ticket.objects.exists())

    def test_draft_cancelled_and_completed_events_are_rejected(self):
        closed_statuses = (
            Event.Status.DRAFT,
            Event.Status.CANCELLED,
            Event.Status.COMPLETED,
        )

        for status in closed_statuses:
            with self.subTest(status=status):
                self.event.status = status
                self.event.save(update_fields=("status",))

                with self.assertRaises(RegistrationClosedError):
                    self.issue()

        self.assertFalse(Ticket.objects.exists())

    def test_event_registration_window_boundaries_are_enforced(self):
        request_times = (
            self.event.registration_opens_at - timedelta(seconds=1),
            self.event.registration_closes_at,
        )

        for request_time in request_times:
            with (
                self.subTest(request_time=request_time),
                self.assertRaises(RegistrationClosedError),
            ):
                self.issue(moment=request_time)

        self.assertFalse(Ticket.objects.exists())

    def test_category_override_can_close_registration_early(self):
        self.category.registration_opens_at = self.now + timedelta(hours=1)
        self.category.registration_closes_at = self.now + timedelta(days=1)
        self.category.save(
            update_fields=(
                "registration_opens_at",
                "registration_closes_at",
            )
        )

        with self.assertRaises(RegistrationClosedError):
            self.issue()

        self.assertFalse(Ticket.objects.exists())

    def test_open_category_override_replaces_closed_event_window(self):
        self.event.registration_opens_at = self.now - timedelta(days=2)
        self.event.registration_closes_at = self.now - timedelta(hours=1)
        self.event.save(
            update_fields=(
                "registration_opens_at",
                "registration_closes_at",
            )
        )
        self.category.registration_opens_at = self.now - timedelta(hours=1)
        self.category.registration_closes_at = self.now + timedelta(hours=1)
        self.category.save(
            update_fields=(
                "registration_opens_at",
                "registration_closes_at",
            )
        )

        result = self.issue()

        self.assertTrue(result.created)

    def test_per_user_limit_counts_only_active_tickets(self):
        self.category.capacity = 3
        self.category.save(update_fields=("capacity",))
        self.issue()

        with self.assertRaises(PerUserLimitReachedError):
            self.issue()

        self.assertEqual(
            Ticket.objects.filter(user=self.user).count(),
            1,
        )

    def test_issued_ticket_can_sell_out_category(self):
        self.category.capacity = 1
        self.category.save(update_fields=("capacity",))
        self.issue()
        other_user = self.create_user(
            "sold-out@example.com",
            verified=True,
        )

        with self.assertRaises(TicketSoldOutError):
            self.issue(user=other_user)

        self.assertEqual(Ticket.objects.count(), 1)

    def test_checked_in_ticket_can_sell_out_category(self):
        self.category.capacity = 1
        self.category.save(update_fields=("capacity",))
        checker = self.create_user(
            "capacity-checker@example.com",
            verified=True,
        )
        self.create_ticket(
            status=Ticket.Status.CHECKED_IN,
            checked_in_at=self.now,
            checked_in_by=checker,
        )
        other_user = self.create_user(
            "checked-in-sold-out@example.com",
            verified=True,
        )

        with self.assertRaises(TicketSoldOutError):
            self.issue(user=other_user)

        self.assertEqual(Ticket.objects.count(), 1)

    def test_cancelled_ticket_releases_capacity_and_user_limit(self):
        self.category.capacity = 1
        self.category.save(update_fields=("capacity",))
        first_result = self.issue()

        cancel_ticket(
            user=self.user,
            ticket_id=first_result.ticket.pk,
            moment=self.now,
        )
        replacement_result = self.issue()

        self.assertTrue(replacement_result.created)
        self.assertNotEqual(
            replacement_result.ticket.pk,
            first_result.ticket.pk,
        )
        self.assertEqual(Ticket.objects.count(), 2)
        self.assertEqual(
            Ticket.objects.filter(
                category=self.category,
                status__in=Ticket.ACTIVE_STATUSES,
            ).count(),
            1,
        )


class TicketCancellationServiceTests(TicketFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.ticket = self.issue().ticket

    def test_cancellation_requires_authentication(self):
        with self.assertRaises(AuthenticationRequiredError):
            cancel_ticket(
                user=AnonymousUser(),
                ticket_id=self.ticket.pk,
                moment=self.now,
            )

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.ISSUED)

    def test_owner_can_cancel_issued_ticket_before_event(self):
        cancellation_time = self.now + timedelta(minutes=10)

        result = cancel_ticket(
            user=self.user,
            ticket_id=self.ticket.pk,
            moment=cancellation_time,
        )

        self.assertTrue(result.cancelled)
        self.assertEqual(result.ticket.pk, self.ticket.pk)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.CANCELLED)
        self.assertEqual(self.ticket.cancelled_at, cancellation_time)
        self.assertIsNone(self.ticket.checked_in_at)
        self.assertFalse(self.ticket.counts_against_capacity)

    def test_cancellation_replay_is_idempotent(self):
        first_time = self.now + timedelta(minutes=10)
        first_result = cancel_ticket(
            user=self.user,
            ticket_id=self.ticket.pk,
            moment=first_time,
        )
        replay_result = cancel_ticket(
            user=self.user,
            ticket_id=self.ticket.pk,
            moment=self.event.starts_at + timedelta(hours=1),
        )

        self.assertTrue(first_result.cancelled)
        self.assertFalse(replay_result.cancelled)
        self.assertEqual(replay_result.ticket.pk, self.ticket.pk)
        self.assertEqual(replay_result.ticket.cancelled_at, first_time)

    def test_checked_in_ticket_cannot_be_cancelled(self):
        checker = self.create_user(
            "cancellation-checker@example.com",
            verified=True,
        )
        self.ticket.status = Ticket.Status.CHECKED_IN
        self.ticket.checked_in_at = self.now
        self.ticket.checked_in_by = checker
        self.ticket.save(
            update_fields=(
                "status",
                "checked_in_at",
                "checked_in_by",
            )
        )

        with self.assertRaises(TicketAlreadyCheckedInError):
            cancel_ticket(
                user=self.user,
                ticket_id=self.ticket.pk,
                moment=self.now,
            )

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.CHECKED_IN)
        self.assertIsNone(self.ticket.cancelled_at)
        self.assertEqual(self.ticket.checked_in_by, checker)

    def test_ticket_cannot_be_cancelled_at_or_after_event_start(self):
        for cancellation_time in (
            self.event.starts_at,
            self.event.starts_at + timedelta(seconds=1),
        ):
            with (
                self.subTest(cancellation_time=cancellation_time),
                self.assertRaises(TicketCancellationClosedError),
            ):
                cancel_ticket(
                    user=self.user,
                    ticket_id=self.ticket.pk,
                    moment=cancellation_time,
                )

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.ISSUED)
        self.assertIsNone(self.ticket.cancelled_at)

    def test_user_cannot_cancel_another_users_ticket(self):
        other_user = self.create_user(
            "not-owner@example.com",
            verified=True,
        )

        with self.assertRaises(TicketNotFoundError):
            cancel_ticket(
                user=other_user,
                ticket_id=self.ticket.pk,
                moment=self.now,
            )

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.ISSUED)

    def test_missing_ticket_is_reported_as_not_found(self):
        with self.assertRaises(TicketNotFoundError):
            cancel_ticket(
                user=self.user,
                ticket_id=uuid4(),
                moment=self.now,
            )


class TicketCheckInServiceTests(TicketFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.organizer = self.create_user(
            "check-in-organizer@example.com",
            verified=True,
        )
        OrganizerProfile.objects.create(
            user=self.organizer,
            organization_name="TUES",
            reason="Check-in service tests.",
            status=OrganizerProfile.Status.APPROVED,
        )
        self.event.organizer = self.organizer
        self.event.save(update_fields=("organizer",))
        self.ticket = self.create_ticket()

    def assert_ticket_remains_issued(self):
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status,
            Ticket.Status.ISSUED,
        )
        self.assertIsNone(self.ticket.cancelled_at)
        self.assertIsNone(self.ticket.checked_in_at)
        self.assertIsNone(self.ticket.checked_in_by)

    def test_check_in_requires_authentication(self):
        with self.assertRaises(AuthenticationRequiredError):
            check_in_ticket(
                user=AnonymousUser(),
                validation_token=self.ticket.validation_token,
                moment=self.now,
            )

        self.assert_ticket_remains_issued()

    def test_approved_event_owner_checks_in_ticket_with_audit(self):
        check_in_time = self.now + timedelta(minutes=15)

        result = check_in_ticket(
            user=self.organizer,
            validation_token=self.ticket.validation_token,
            moment=check_in_time,
        )

        self.assertEqual(result.ticket.pk, self.ticket.pk)
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status,
            Ticket.Status.CHECKED_IN,
        )
        self.assertEqual(
            self.ticket.checked_in_at,
            check_in_time,
        )
        self.assertEqual(
            self.ticket.checked_in_by,
            self.organizer,
        )
        self.assertIsNone(self.ticket.cancelled_at)

    def test_user_with_global_permission_can_check_in_foreign_event(self):
        global_checker = self.create_user(
            "global-checker@example.com",
            verified=True,
        )
        permission = Permission.objects.get(
            content_type__app_label="tickets",
            codename="check_in_ticket",
        )
        global_checker.user_permissions.add(permission)
        check_in_time = self.now + timedelta(minutes=20)

        result = check_in_ticket(
            user=global_checker,
            validation_token=self.ticket.validation_token,
            moment=check_in_time,
        )

        self.assertEqual(result.ticket.pk, self.ticket.pk)
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status,
            Ticket.Status.CHECKED_IN,
        )
        self.assertEqual(
            self.ticket.checked_in_at,
            check_in_time,
        )
        self.assertEqual(
            self.ticket.checked_in_by,
            global_checker,
        )

    def test_plain_staff_user_cannot_check_in_ticket(self):
        staff_user = self.create_user(
            "plain-staff@example.com",
            verified=True,
        )
        staff_user.is_staff = True
        staff_user.save(update_fields=("is_staff",))

        with self.assertRaises(TicketNotFoundError):
            check_in_ticket(
                user=staff_user,
                validation_token=self.ticket.validation_token,
                moment=self.now,
            )

        self.assert_ticket_remains_issued()

    def test_unapproved_event_owner_cannot_check_in_ticket(self):
        profile = self.organizer.organizer_profile
        profile.status = OrganizerProfile.Status.PENDING
        profile.save(update_fields=("status",))

        with self.assertRaises(TicketNotFoundError):
            check_in_ticket(
                user=self.organizer,
                validation_token=self.ticket.validation_token,
                moment=self.now,
            )

        self.assert_ticket_remains_issued()

    def test_approved_foreign_organizer_cannot_check_in_ticket(self):
        foreign_organizer = self.create_user(
            "foreign-organizer@example.com",
            verified=True,
        )
        OrganizerProfile.objects.create(
            user=foreign_organizer,
            organization_name="Another organization",
            reason="Foreign organizer authorization test.",
            status=OrganizerProfile.Status.APPROVED,
        )

        with self.assertRaises(TicketNotFoundError):
            check_in_ticket(
                user=foreign_organizer,
                validation_token=self.ticket.validation_token,
                moment=self.now,
            )

        self.assert_ticket_remains_issued()

    def test_unknown_validation_token_is_not_found(self):
        unknown_token = token_urlsafe(32)
        self.assertNotEqual(
            unknown_token,
            self.ticket.validation_token,
        )

        with self.assertRaises(TicketNotFoundError):
            check_in_ticket(
                user=self.organizer,
                validation_token=unknown_token,
                moment=self.now,
            )

        self.assert_ticket_remains_issued()

    def test_malformed_validation_tokens_are_not_found(self):
        invalid_tokens = (
            None,
            uuid4(),
            "",
            "too-short",
            "a" * 42,
            "a" * 44,
            "!" * 43,
        )

        for validation_token in invalid_tokens:
            with (
                self.subTest(validation_token=validation_token),
                self.assertRaises(TicketNotFoundError),
            ):
                check_in_ticket(
                    user=self.organizer,
                    validation_token=validation_token,
                    moment=self.now,
                )

        self.assert_ticket_remains_issued()

    def test_cancelled_ticket_cannot_be_checked_in(self):
        cancellation_time = self.now - timedelta(minutes=10)
        self.ticket.status = Ticket.Status.CANCELLED
        self.ticket.cancelled_at = cancellation_time
        self.ticket.save(
            update_fields=(
                "status",
                "cancelled_at",
            )
        )

        with self.assertRaises(TicketCancelledCheckInError):
            check_in_ticket(
                user=self.organizer,
                validation_token=self.ticket.validation_token,
                moment=self.now,
            )

        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status,
            Ticket.Status.CANCELLED,
        )
        self.assertEqual(
            self.ticket.cancelled_at,
            cancellation_time,
        )
        self.assertIsNone(self.ticket.checked_in_at)
        self.assertIsNone(self.ticket.checked_in_by)

    def test_already_checked_in_ticket_preserves_original_audit(self):
        original_checker = self.create_user(
            "original-checker@example.com",
            verified=True,
        )
        original_check_in_time = self.now - timedelta(minutes=30)
        self.ticket.status = Ticket.Status.CHECKED_IN
        self.ticket.checked_in_at = original_check_in_time
        self.ticket.checked_in_by = original_checker
        self.ticket.save(
            update_fields=(
                "status",
                "checked_in_at",
                "checked_in_by",
            )
        )

        with self.assertRaises(
            TicketAlreadyCheckedInForEntryError
        ):
            check_in_ticket(
                user=self.organizer,
                validation_token=self.ticket.validation_token,
                moment=self.now,
            )

        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.status,
            Ticket.Status.CHECKED_IN,
        )
        self.assertEqual(
            self.ticket.checked_in_at,
            original_check_in_time,
        )
        self.assertEqual(
            self.ticket.checked_in_by,
            original_checker,
        )
        self.assertIsNone(self.ticket.cancelled_at)

    def test_cancelled_event_rejects_check_in_without_audit(self):
        self.event.status = Event.Status.CANCELLED
        self.event.save(update_fields=("status",))

        with self.assertRaises(EventCheckInUnavailableError):
            check_in_ticket(
                user=self.organizer,
                validation_token=self.ticket.validation_token,
                moment=self.now,
            )

        self.assert_ticket_remains_issued()

    def test_event_end_boundary_rejects_check_in_without_audit(self):
        for check_in_time in (
            self.event.ends_at,
            self.event.ends_at + timedelta(seconds=1),
        ):
            with (
                self.subTest(check_in_time=check_in_time),
                self.assertRaises(EventCheckInUnavailableError),
            ):
                check_in_ticket(
                    user=self.organizer,
                    validation_token=self.ticket.validation_token,
                    moment=check_in_time,
                )

        self.assert_ticket_remains_issued()
