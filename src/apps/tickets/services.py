from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.verification import is_user_email_verified
from apps.events.models import Event, TicketCategory

from .models import Ticket


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


@dataclass(frozen=True, slots=True)
class TicketAllocationResult:
    ticket: Ticket
    created: bool


@dataclass(frozen=True, slots=True)
class TicketCancellationResult:
    ticket: Ticket
    cancelled: bool


def _normalise_idempotency_key(value):
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise InvalidIdempotencyKeyError from error


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
        ticket.save(
            update_fields=(
                "status",
                "cancelled_at",
            )
        )

        return TicketCancellationResult(
            ticket=ticket,
            cancelled=True,
        )
