from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings
from django.core.files.storage import storages
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .filenames import ticket_download_filename
from .models import TicketEmailDelivery
from .pdf_service import (
    TicketPdfError,
    TicketPdfUnavailableError,
    get_or_generate_ticket_pdf,
)


class TicketEmailDeliveryError(Exception):
    pass


class TicketEmailDeliveryTransientError(
    TicketEmailDeliveryError
):
    pass


@dataclass(frozen=True, slots=True)
class TicketEmailAttempt:
    delivery_id: str
    ticket_id: str
    recipient: str
    message_token: str
    attempt_count: int


def _ticket_is_sendable(delivery, moment):
    return delivery.ticket.is_valid_for_entry_at(moment)


def _claim_delivery(delivery_id):
    attempt_time = timezone.now()

    with transaction.atomic():
        try:
            delivery = (
                TicketEmailDelivery.objects.select_for_update()
                .select_related(
                    "ticket__user",
                    "ticket__category__event",
                )
                .get(pk=delivery_id)
            )
        except TicketEmailDelivery.DoesNotExist:
            return None

        if delivery.status in (
            TicketEmailDelivery.Status.SENT,
            TicketEmailDelivery.Status.CANCELLED,
        ):
            return None

        if (
            delivery.status
            == TicketEmailDelivery.Status.SENDING
            and delivery.last_attempt_at is not None
            and attempt_time
            < delivery.last_attempt_at
            + settings.TICKET_EMAIL_STALE_AFTER
        ):
            return None

        if (
            delivery.attempt_count
            > settings.EMAIL_DELIVERY_MAX_RETRIES
        ):
            delivery.status = TicketEmailDelivery.Status.FAILED
            delivery.save(update_fields=("status",))
            return None

        if not _ticket_is_sendable(delivery, attempt_time):
            delivery.status = (
                TicketEmailDelivery.Status.CANCELLED
            )
            delivery.sent_at = None
            delivery.save(
                update_fields=("status", "sent_at")
            )
            return None

        delivery.status = TicketEmailDelivery.Status.SENDING
        delivery.attempt_count += 1
        delivery.last_attempt_at = attempt_time
        delivery.last_error = ""
        delivery.save(
            update_fields=(
                "status",
                "attempt_count",
                "last_attempt_at",
                "last_error",
            )
        )

        return TicketEmailAttempt(
            delivery_id=str(delivery.pk),
            ticket_id=str(delivery.ticket_id),
            recipient=delivery.recipient,
            message_token=str(delivery.message_token),
            attempt_count=delivery.attempt_count,
        )


def _mark_cancelled(delivery_id):
    TicketEmailDelivery.objects.filter(
        pk=delivery_id,
    ).exclude(
        status=TicketEmailDelivery.Status.SENT,
    ).update(
        status=TicketEmailDelivery.Status.CANCELLED,
        sent_at=None,
    )


def _mark_failed(delivery_id, error):
    error_message = str(error).strip()

    if not error_message:
        error_message = error.__class__.__name__

    TicketEmailDelivery.objects.filter(
        pk=delivery_id,
        status=TicketEmailDelivery.Status.SENDING,
    ).update(
        status=TicketEmailDelivery.Status.FAILED,
        sent_at=None,
        last_error=error_message[:2_000],
    )


def _mark_sent(delivery_id):
    TicketEmailDelivery.objects.filter(
        pk=delivery_id,
    ).update(
        status=TicketEmailDelivery.Status.SENT,
        sent_at=timezone.now(),
        last_error="",
    )


def _delivery_remains_sendable(delivery_id):
    with transaction.atomic():
        try:
            delivery = (
                TicketEmailDelivery.objects.select_for_update()
                .select_related("ticket__category__event")
                .get(pk=delivery_id)
            )
        except TicketEmailDelivery.DoesNotExist:
            return False

        if (
            delivery.status
            != TicketEmailDelivery.Status.SENDING
        ):
            return False

        if not _ticket_is_sendable(delivery, timezone.now()):
            delivery.status = (
                TicketEmailDelivery.Status.CANCELLED
            )
            delivery.sent_at = None
            delivery.save(
                update_fields=("status", "sent_at")
            )
            return False

        return True


def _message_id(message_token):
    hostname = urlsplit(settings.APP_BASE_URL).hostname
    hostname = hostname or "localhost"
    return f"<ticket-{message_token}@{hostname}>"


def _build_message(delivery, pdf_bytes):
    ticket = delivery.ticket
    event = ticket.category.event
    my_tickets_url = (
        f"{settings.APP_BASE_URL}"
        f"{reverse('tickets:my_tickets')}"
    )
    context = {
        "ticket": ticket,
        "event": event,
        "category": ticket.category,
        "holder_name": (
            ticket.user.get_full_name().strip()
            or ticket.user.email
        ),
        "my_tickets_url": my_tickets_url,
    }
    event_name = " ".join(event.name.splitlines())
    message = EmailMultiAlternatives(
        subject=f"Your ticket for {event_name}",
        body=render_to_string(
            "tickets/email/ticket.txt",
            context,
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[delivery.recipient],
        headers={
            "Message-ID": _message_id(
                str(delivery.message_token)
            ),
        },
    )
    message.attach_alternative(
        render_to_string(
            "tickets/email/ticket.html",
            context,
        ),
        "text/html",
    )
    message.attach(
        ticket_download_filename(ticket),
        pdf_bytes,
        "application/pdf",
    )
    return message


def perform_ticket_email_delivery(delivery_id):
    attempt = _claim_delivery(delivery_id)

    if attempt is None:
        return False

    try:
        delivery = (
            TicketEmailDelivery.objects.select_related(
                "ticket__user",
                "ticket__category__event",
            ).get(pk=attempt.delivery_id)
        )
        pdf_result = get_or_generate_ticket_pdf(
            user=delivery.ticket.user,
            ticket_id=delivery.ticket_id,
        )

        with storages["ticket_pdfs"].open(
            pdf_result.storage_name,
            "rb",
        ) as pdf_file:
            pdf_bytes = pdf_file.read(
                settings.MAX_TICKET_FILE_SIZE + 1
            )

        if len(pdf_bytes) > settings.MAX_TICKET_FILE_SIZE:
            raise TicketEmailDeliveryTransientError(
                "The generated ticket PDF is too large."
            )

        if not _delivery_remains_sendable(attempt.delivery_id):
            return False

        sent_count = _build_message(
            delivery,
            pdf_bytes,
        ).send(fail_silently=False)

        if sent_count != 1:
            raise TicketEmailDeliveryTransientError(
                "The email backend did not confirm delivery."
            )
    except TicketPdfUnavailableError:
        _mark_cancelled(attempt.delivery_id)
        return False
    except (TicketPdfError, OSError, ValueError) as error:
        _mark_failed(attempt.delivery_id, error)
        raise TicketEmailDeliveryTransientError from error
    except Exception as error:
        _mark_failed(attempt.delivery_id, error)
        raise TicketEmailDeliveryTransientError from error

    _mark_sent(attempt.delivery_id)
    return True
