from celery import shared_task
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .emailing import (
    TicketEmailDeliveryTransientError,
    perform_ticket_email_delivery,
)
from .models import TicketEmailDelivery, TicketRequest
from .queueing import process_next_ticket_request


@shared_task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=30,
    max_retries=8,
)
def process_ticket_queue(self, category_id, batch_size=100):
    processed = 0

    while processed < batch_size:
        ticket_request = process_next_ticket_request(category_id)

        if ticket_request is None:
            break

        processed += 1

    if TicketRequest.objects.filter(
        category_id=category_id,
        status=TicketRequest.Status.PENDING,
    ).exists():
        process_ticket_queue.delay(category_id)

    return processed


@shared_task(
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def dispatch_pending_ticket_requests():
    category_ids = list(
        TicketRequest.objects.filter(
            status=TicketRequest.Status.PENDING,
        )
        .order_by("category_id")
        .values_list("category_id", flat=True)
        .distinct()[:200]
    )

    for category_id in category_ids:
        process_ticket_queue.delay(category_id)

    return len(category_ids)


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
