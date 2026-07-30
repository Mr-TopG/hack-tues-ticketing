from dataclasses import dataclass
from re import fullmatch
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import OrganizerProfile
from apps.accounts.verification import is_user_email_verified
from apps.events.models import Event, TicketCategory

from .models import Ticket
from .storage import clear_ticket_pdf_metadata


class TicketServiceError(Exception):
    default_message = "The ticket request could not be completed."

    def __init__(self, message=None):
        super().__init__(message or self.default_message)


class AuthenticationRequiredError(TicketServiceError):
    default_message = "Log in before requesting a ticket."


class EmailNotVerifiedError(TicketServiceError):
    default_message = "Verify your primary email before requesting a ticket."


class InvalidIdempotencyKeyError(TicketServiceError):
    default_message = "This ticket request is invalid. Please try again."


class IdempotencyConflictError(TicketServiceError):
    default_message = (
        "This ticket request has already been used for another account "
        "or ticket category."
    )


class InactiveTicketCategoryError(TicketServiceError):
    default_message = "This ticket category is not available."


class RegistrationClosedError(TicketServiceError):
    default_message = "Registration is not open for this ticket category."


class TicketSoldOutError(TicketServiceError):
    default_message = "This ticket category is sold out."


class PerUserLimitReachedError(TicketServiceError):
    default_message = "You have reached the ticket limit for this category."


class TicketNotFoundError(TicketServiceError):
    default_message = "The requested ticket was not found."


class TicketCancellationError(TicketServiceError):
    default_message = "This ticket cannot be cancelled."


class TicketAlreadyCheckedInError(TicketCancellationError):
    default_message = "A checked-in ticket cannot be cancelled."


class TicketCancellationClosedError(TicketCancellationError):
    default_message = "Tickets cannot be cancelled after the event starts."


class TicketCheckInError(TicketServiceError):
    default_message = "This ticket cannot be checked in."


class TicketCancelledCheckInError(TicketCheckInError):
    default_message = "A cancelled ticket cannot be checked in."


class TicketAlreadyCheckedInForEntryError(TicketCheckInError):
    default_message = "This ticket has already been checked in."


class EventCheckInUnavailableError(TicketCheckInError):
    default_message = "Check-in is unavailable for this event."


@dataclass(frozen=True, slots=True)
class TicketAllocationResult:
    ticket: Ticket
    created: bool


@dataclass(frozen=True, slots=True)
class TicketCancellationResult:
    ticket: Ticket
    cancelled: bool


@dataclass(frozen=True, slots=True)
class TicketCheckInResult:
    ticket: Ticket


def _normalise_idempotency_key(value):
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise InvalidIdempotencyKeyError from error


def _normalise_validation_token(value):
    if not isinstance(value, str):
        raise TicketNotFoundError

    token = value.strip()

    if (
        len(token) != 43
        or fullmatch(r"[A-Za-z0-9_-]+", token) is None
    ):
        raise TicketNotFoundError

    return token


def user_can_access_ticket_check_in(user):
    if (
        not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
    ):
        return False

    if user.has_perm("tickets.check_in_ticket"):
        return True

    return OrganizerProfile.objects.filter(
        user_id=user.pk,
        status=OrganizerProfile.Status.APPROVED,
    ).exists()


def user_can_check_in_for_event(*, user, event):
    if (
        not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
    ):
        return False

    if user.has_perm("tickets.check_in_ticket"):
        return True

    return (
        event.organizer_id == user.pk
        and OrganizerProfile.objects.filter(
            user_id=user.pk,
            status=OrganizerProfile.Status.APPROVED,
        ).exists()
    )


def get_ticket_for_check_in(*, user, validation_token):
    if not getattr(user, "is_authenticated", False):
        raise AuthenticationRequiredError

    token = _normalise_validation_token(validation_token)
    ticket = (
        Ticket.objects.select_related(
            "user",
            "category__event",
            "checked_in_by",
        )
        .filter(validation_token=token)
        .first()
    )

    if (
        ticket is None
        or not user_can_check_in_for_event(
            user=user,
            event=ticket.category.event,
        )
    ):
        raise TicketNotFoundError

    return ticket


def _resolve_existing_ticket(*, ticket, user_id, category_id):
    if (
        ticket.user_id != user_id
        or ticket.category_id != category_id
    ):
        raise IdempotencyConflictError

    return TicketAllocationResult(
        ticket=ticket,
        created=False,
    )


def issue_ticket(
    *,
    user,
    category_id,
    idempotency_key,
    moment=None,
):
    if not getattr(user, "is_authenticated", False):
        raise AuthenticationRequiredError

    key = _normalise_idempotency_key(idempotency_key)
    user_id = user.pk

    with transaction.atomic():
        category = TicketCategory.objects.select_for_update(
            of=("self",)
        ).get(
            pk=category_id
        )
        category.event = Event.objects.get(pk=category.event_id)

        existing_ticket = (
            Ticket.objects.select_related("category__event")
            .filter(idempotency_key=key)
            .first()
        )

        if existing_ticket is not None:
            return _resolve_existing_ticket(
                ticket=existing_ticket,
                user_id=user_id,
                category_id=category.pk,
            )

        if not is_user_email_verified(user):
            raise EmailNotVerifiedError

        if not category.is_active:
            raise InactiveTicketCategoryError

        request_time = moment or timezone.now()

        if (
            category.event.status != Event.Status.PUBLISHED
            or not category.registration_is_open_at(request_time)
        ):
            raise RegistrationClosedError

        active_tickets = Ticket.objects.filter(
            category_id=category.pk,
            status__in=Ticket.ACTIVE_STATUSES,
        )

        if active_tickets.count() >= category.capacity:
            raise TicketSoldOutError

        if (
            active_tickets.filter(user_id=user_id).count()
            >= category.per_user_limit
        ):
            raise PerUserLimitReachedError

        try:
            with transaction.atomic():
                ticket = Ticket.objects.create(
                    user_id=user_id,
                    category=category,
                    idempotency_key=key,
                )
        except IntegrityError:
            existing_ticket = (
                Ticket.objects.select_related("category__event")
                .filter(idempotency_key=key)
                .first()
            )

            if existing_ticket is None:
                raise

            return _resolve_existing_ticket(
                ticket=existing_ticket,
                user_id=user_id,
                category_id=category.pk,
            )

        return TicketAllocationResult(
            ticket=ticket,
            created=True,
        )


def cancel_ticket(*, user, ticket_id, moment=None):
    if not getattr(user, "is_authenticated", False):
        raise AuthenticationRequiredError

    ticket_reference = (
        Ticket.objects.filter(
            pk=ticket_id,
            user_id=user.pk,
        )
        .values("pk", "category_id")
        .first()
    )

    if ticket_reference is None:
        raise TicketNotFoundError

    with transaction.atomic():
        category = TicketCategory.objects.select_for_update(
            of=("self",)
        ).get(
            pk=ticket_reference["category_id"]
        )
        category.event = Event.objects.get(pk=category.event_id)

        try:
            ticket = (
                Ticket.objects.select_for_update(of=("self",))
                .select_related("category__event")
                .get(
                    pk=ticket_reference["pk"],
                    user_id=user.pk,
                    category_id=category.pk,
                )
            )
        except Ticket.DoesNotExist as error:
            raise TicketNotFoundError from error

        if ticket.status == Ticket.Status.CANCELLED:
            return TicketCancellationResult(
                ticket=ticket,
                cancelled=False,
            )

        if ticket.status == Ticket.Status.CHECKED_IN:
            raise TicketAlreadyCheckedInError

        if ticket.status != Ticket.Status.ISSUED:
            raise TicketCancellationError

        cancellation_time = moment or timezone.now()

        if cancellation_time >= category.event.starts_at:
            raise TicketCancellationClosedError

        ticket.status = Ticket.Status.CANCELLED
        ticket.cancelled_at = cancellation_time
        clear_ticket_pdf_metadata(ticket)
        ticket.save(
            update_fields=(
                "status",
                "cancelled_at",
                "pdf_storage_name",
                "pdf_source_hash",
                "pdf_generated_at",
            )
        )

        return TicketCancellationResult(
            ticket=ticket,
            cancelled=True,
        )


def check_in_ticket(
    *,
    user,
    validation_token,
    moment=None,
):
    if not getattr(user, "is_authenticated", False):
        raise AuthenticationRequiredError

    token = _normalise_validation_token(validation_token)
    ticket_reference = (
        Ticket.objects.filter(validation_token=token)
        .values("pk", "category_id")
        .first()
    )

    if ticket_reference is None:
        raise TicketNotFoundError

    with transaction.atomic():
        category = TicketCategory.objects.select_for_update(
            of=("self",)
        ).get(pk=ticket_reference["category_id"])
        category.event = Event.objects.get(pk=category.event_id)

        if not user_can_check_in_for_event(
            user=user,
            event=category.event,
        ):
            raise TicketNotFoundError

        try:
            ticket = (
                Ticket.objects.select_for_update(of=("self",))
                .select_related(
                    "user",
                    "category__event",
                    "checked_in_by",
                )
                .get(
                    pk=ticket_reference["pk"],
                    category_id=category.pk,
                    validation_token=token,
                )
            )
        except Ticket.DoesNotExist as error:
            raise TicketNotFoundError from error

        if ticket.status == Ticket.Status.CANCELLED:
            raise TicketCancelledCheckInError

        if ticket.status == Ticket.Status.CHECKED_IN:
            raise TicketAlreadyCheckedInForEntryError

        if ticket.status != Ticket.Status.ISSUED:
            raise TicketCheckInError

        check_in_time = moment or timezone.now()

        if (
            category.event.status != Event.Status.PUBLISHED
            or check_in_time >= category.event.ends_at
        ):
            raise EventCheckInUnavailableError

        ticket.status = Ticket.Status.CHECKED_IN
        ticket.checked_in_at = check_in_time
        ticket.checked_in_by = user
        clear_ticket_pdf_metadata(ticket)
        ticket.save(
            update_fields=(
                "status",
                "checked_in_at",
                "checked_in_by",
                "pdf_storage_name",
                "pdf_source_hash",
                "pdf_generated_at",
            )
        )

        return TicketCheckInResult(ticket=ticket)
