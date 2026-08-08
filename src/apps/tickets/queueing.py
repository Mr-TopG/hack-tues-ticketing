import logging
from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.verification import is_user_email_verified
from apps.events.models import Event, TicketCategory

from .models import Ticket, TicketRequest
from .services import (
    AuthenticationRequiredError,
    EmailNotVerifiedError,
    IdempotencyConflictError,
    InactiveTicketCategoryError,
    InvalidIdempotencyKeyError,
    RegistrationClosedError,
    TicketServiceError,
    issue_ticket,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TicketRequestEnqueueResult:
    ticket_request: TicketRequest
    created: bool


def _normalise_idempotency_key(value):
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise InvalidIdempotencyKeyError from error


def _resolve_existing_request(
    *,
    ticket_request,
    user_id,
    category_id,
):
    if (
        ticket_request.user_id != user_id
        or ticket_request.category_id != category_id
    ):
        raise IdempotencyConflictError

    return TicketRequestEnqueueResult(
        ticket_request=ticket_request,
        created=False,
    )


def _enqueue_task(category_id):
    try:
        from .tasks import process_ticket_queue

        process_ticket_queue.delay(category_id)
    except Exception:
        logger.exception(
            "Could not enqueue ticket request processor for category %s.",
            category_id,
        )


def schedule_ticket_queue(category_id):
    transaction.on_commit(lambda: _enqueue_task(category_id))


def enqueue_ticket_request(
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
    existing_request = TicketRequest.objects.filter(
        idempotency_key=key,
    ).first()

    if existing_request is not None:
        return _resolve_existing_request(
            ticket_request=existing_request,
            user_id=user_id,
            category_id=category_id,
        )

    with transaction.atomic():
        category = (
            TicketCategory.objects.select_for_update(of=("self",))
            .select_related("event")
            .get(pk=category_id)
        )

        existing_request = TicketRequest.objects.filter(
            idempotency_key=key,
        ).first()

        if existing_request is not None:
            return _resolve_existing_request(
                ticket_request=existing_request,
                user_id=user_id,
                category_id=category.pk,
            )

        existing_ticket = Ticket.objects.filter(
            idempotency_key=key,
        ).first()

        if existing_ticket is not None:
            if (
                existing_ticket.user_id != user_id
                or existing_ticket.category_id != category.pk
            ):
                raise IdempotencyConflictError

            ticket_request = TicketRequest.objects.create(
                user_id=user_id,
                category=category,
                idempotency_key=key,
                status=TicketRequest.Status.SUCCEEDED,
                ticket=existing_ticket,
                completed_at=timezone.now(),
            )
            return TicketRequestEnqueueResult(
                ticket_request=ticket_request,
                created=False,
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

        try:
            with transaction.atomic():
                ticket_request = TicketRequest.objects.create(
                    user_id=user_id,
                    category=category,
                    idempotency_key=key,
                )
        except IntegrityError:
            existing_request = TicketRequest.objects.filter(
                idempotency_key=key,
            ).first()

            if existing_request is None:
                raise

            return _resolve_existing_request(
                ticket_request=existing_request,
                user_id=user_id,
                category_id=category.pk,
            )

        schedule_ticket_queue(category.pk)
        return TicketRequestEnqueueResult(
            ticket_request=ticket_request,
            created=True,
        )


def process_next_ticket_request(category_id):
    with transaction.atomic():
        try:
            category = TicketCategory.objects.select_for_update(
                of=("self",)
            ).get(pk=category_id)
        except TicketCategory.DoesNotExist:
            return None

        ticket_request = (
            TicketRequest.objects.select_for_update(of=("self",))
            .select_related("user")
            .filter(
                category=category,
                status=TicketRequest.Status.PENDING,
            )
            .order_by("id")
            .first()
        )

        if ticket_request is None:
            return None

        completed_at = timezone.now()

        try:
            result = issue_ticket(
                user=ticket_request.user,
                category_id=category.pk,
                idempotency_key=ticket_request.idempotency_key,
                moment=ticket_request.requested_at,
            )
        except TicketServiceError as error:
            ticket_request.status = TicketRequest.Status.REJECTED
            ticket_request.failure_code = error.__class__.__name__
            ticket_request.failure_message = str(error)
            ticket_request.completed_at = completed_at
            ticket_request.save(
                update_fields=(
                    "status",
                    "failure_code",
                    "failure_message",
                    "completed_at",
                )
            )
        else:
            ticket_request.status = TicketRequest.Status.SUCCEEDED
            ticket_request.ticket = result.ticket
            ticket_request.completed_at = completed_at
            ticket_request.save(
                update_fields=(
                    "status",
                    "ticket",
                    "completed_at",
                )
            )

        return ticket_request


def ticket_request_queue_position(ticket_request):
    if ticket_request.status != TicketRequest.Status.PENDING:
        return 0

    return TicketRequest.objects.filter(
        category_id=ticket_request.category_id,
        status=TicketRequest.Status.PENDING,
        id__lt=ticket_request.id,
    ).count() + 1
