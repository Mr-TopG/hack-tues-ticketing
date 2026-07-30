import logging
from dataclasses import dataclass
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.verification import is_user_email_verified
from apps.events.models import Event, TicketCategory

from .models import Ticket, TicketEmailDelivery

logger = logging.getLogger(__name__)


class TicketEmailRequestError(Exception):
    default_message = "The ticket email could not be requested."

    def __init__(self, message=None):
        super().__init__(message or self.default_message)


class TicketEmailAuthenticationRequiredError(
    TicketEmailRequestError
):
    default_message = "Log in before requesting a ticket email."


class TicketEmailNotFoundError(TicketEmailRequestError):
    default_message = "The requested ticket was not found."


class TicketEmailUnavailableError(TicketEmailRequestError):
    default_message = "Email delivery is unavailable for this ticket."


class TicketEmailCooldownError(TicketEmailRequestError):
    default_message = (
        "Please wait before requesting another ticket email."
    )


@dataclass(frozen=True, slots=True)
class TicketEmailRequestResult:
    delivery: TicketEmailDelivery
    queued: bool


def _enqueue_delivery(delivery_id):
    try:
        from .tasks import send_ticket_email

        send_ticket_email.delay(str(delivery_id))
    except Exception:
        logger.exception(
            "Could not enqueue ticket email delivery %s.",
            delivery_id,
        )


def schedule_ticket_email_delivery(delivery_id):
    transaction.on_commit(
        lambda: _enqueue_delivery(delivery_id),
    )


def create_ticket_email_delivery(ticket):
    delivery = TicketEmailDelivery.objects.create(
        ticket=ticket,
        recipient=ticket.user.email,
    )
    schedule_ticket_email_delivery(delivery.pk)
    return delivery


def cancel_ticket_email_delivery(ticket):
    TicketEmailDelivery.objects.filter(
        ticket_id=ticket.pk,
        status__in=(
            TicketEmailDelivery.Status.PENDING,
            TicketEmailDelivery.Status.SENDING,
            TicketEmailDelivery.Status.FAILED,
        ),
    ).update(
        status=TicketEmailDelivery.Status.CANCELLED,
        sent_at=None,
    )


def request_ticket_email(*, user, ticket_id, moment=None):
    if not getattr(user, "is_authenticated", False):
        raise TicketEmailAuthenticationRequiredError

    request_time = moment or timezone.now()
    ticket_reference = (
        Ticket.objects.filter(
            pk=ticket_id,
            user_id=user.pk,
        )
        .values("pk", "category_id")
        .first()
    )

    if ticket_reference is None:
        raise TicketEmailNotFoundError

    with transaction.atomic():
        category = TicketCategory.objects.select_for_update(
            of=("self",)
        ).get(pk=ticket_reference["category_id"])
        category.event = Event.objects.get(pk=category.event_id)

        try:
            ticket = (
                Ticket.objects.select_for_update(of=("self",))
                .select_related("user")
                .get(
                    pk=ticket_reference["pk"],
                    user_id=user.pk,
                    category_id=category.pk,
                )
            )
        except Ticket.DoesNotExist as error:
            raise TicketEmailNotFoundError from error

        ticket.category = category

        if (
            not ticket.is_valid_for_entry_at(request_time)
            or not is_user_email_verified(user)
        ):
            raise TicketEmailUnavailableError

        delivery, created = (
            TicketEmailDelivery.objects.select_for_update()
            .get_or_create(
                ticket=ticket,
                defaults={"recipient": user.email},
            )
        )

        if (
            not created
            and delivery.status
            in (
                TicketEmailDelivery.Status.PENDING,
                TicketEmailDelivery.Status.SENDING,
            )
        ):
            return TicketEmailRequestResult(
                delivery=delivery,
                queued=False,
            )

        cooldown = settings.TICKET_EMAIL_RESEND_COOLDOWN

        if (
            not created
            and delivery.last_attempt_at is not None
            and request_time
            < delivery.last_attempt_at
            + cooldown
        ):
            raise TicketEmailCooldownError

        if not created:
            delivery.recipient = user.email
            delivery.status = TicketEmailDelivery.Status.PENDING
            delivery.message_token = uuid4()
            delivery.attempt_count = 0
            delivery.requested_at = request_time
            delivery.last_attempt_at = None
            delivery.sent_at = None
            delivery.last_error = ""
            delivery.save(
                update_fields=(
                    "recipient",
                    "status",
                    "message_token",
                    "attempt_count",
                    "requested_at",
                    "last_attempt_at",
                    "sent_at",
                    "last_error",
                )
            )

        schedule_ticket_email_delivery(delivery.pk)

        return TicketEmailRequestResult(
            delivery=delivery,
            queued=True,
        )
