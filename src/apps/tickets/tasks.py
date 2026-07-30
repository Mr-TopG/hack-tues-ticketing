from celery import shared_task
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .emailing import (
    TicketEmailDeliveryTransientError,
    perform_ticket_email_delivery,
)
from .models import TicketEmailDelivery


@shared_task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def send_ticket_email(self, delivery_id):
    try:
        return perform_ticket_email_delivery(delivery_id)
    except TicketEmailDeliveryTransientError as error:
        try:
            delivery = TicketEmailDelivery.objects.get(
                pk=delivery_id
            )
        except TicketEmailDelivery.DoesNotExist:
            return False

        if (
            delivery.attempt_count
            > settings.EMAIL_DELIVERY_MAX_RETRIES
        ):
            return False

        countdown = min(
            60 * (2 ** max(delivery.attempt_count - 1, 0)),
            600,
        )
        raise self.retry(
            exc=error,
            countdown=countdown,
            max_retries=settings.EMAIL_DELIVERY_MAX_RETRIES,
        ) from error


@shared_task(
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def dispatch_pending_ticket_emails():
    stale_before = (
        timezone.now() - settings.TICKET_EMAIL_STALE_AFTER
    )
    delivery_ids = list(
        TicketEmailDelivery.objects.filter(
            Q(status=TicketEmailDelivery.Status.PENDING)
            | Q(
                status=TicketEmailDelivery.Status.SENDING,
                last_attempt_at__lte=stale_before,
            )
            | Q(
                status=TicketEmailDelivery.Status.FAILED,
                attempt_count__lte=(
                    settings.EMAIL_DELIVERY_MAX_RETRIES
                ),
                last_attempt_at__lte=stale_before,
            )
        )
        .order_by("requested_at")
        .values_list("pk", flat=True)[:200]
    )

    for delivery_id in delivery_ids:
        send_ticket_email.delay(str(delivery_id))

    return len(delivery_ids)
