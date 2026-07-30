from dataclasses import dataclass
from functools import partial
from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import transaction
from django.utils import timezone

from apps.events.models import Event, TicketCategory

from .models import Ticket
from .pdf import (
    build_ticket_pdf_source,
    render_ticket_pdf,
    ticket_pdf_source_hash,
)
from .services import (
    AuthenticationRequiredError,
    TicketNotFoundError,
    TicketServiceError,
)
from .storage import delete_ticket_pdf


class TicketPdfError(TicketServiceError):
    default_message = "The ticket PDF could not be prepared."


class TicketPdfUnavailableError(TicketPdfError):
    default_message = "A PDF is not available for this ticket."


class TicketPdfGenerationError(TicketPdfError):
    default_message = (
        "The ticket PDF could not be generated. Please try again."
    )


@dataclass(frozen=True, slots=True)
class TicketPdfResult:
    ticket: Ticket
    storage_name: str
    generated: bool


def _ticket_queryset():
    return Ticket.objects.select_related(
        "user",
        "category__event",
    )


def get_or_generate_ticket_pdf(*, user, ticket_id, moment=None):
    if not getattr(user, "is_authenticated", False):
        raise AuthenticationRequiredError

    request_time = moment or timezone.now()
    ticket = (
        _ticket_queryset()
        .filter(
            pk=ticket_id,
            user_id=user.pk,
        )
        .first()
    )

    if ticket is None:
        raise TicketNotFoundError

    if not ticket.is_valid_for_entry_at(request_time):
        raise TicketPdfUnavailableError

    preliminary_source = build_ticket_pdf_source(ticket)
    preliminary_hash = ticket_pdf_source_hash(preliminary_source)
    storage = storages["ticket_pdfs"]
    preliminary_pdf = None

    try:
        if not (
            ticket.pdf_storage_name
            and ticket.pdf_source_hash == preliminary_hash
            and storage.exists(ticket.pdf_storage_name)
        ):
            preliminary_pdf = render_ticket_pdf(
                preliminary_source
            )
    except Exception as error:
        raise TicketPdfGenerationError from error

    new_storage_name = ""

    try:
        with transaction.atomic():
            category = TicketCategory.objects.select_for_update(
                of=("self",)
            ).get(pk=ticket.category_id)
            category.event = Event.objects.get(
                pk=category.event_id
            )

            try:
                current_ticket = (
                    Ticket.objects.select_for_update(of=("self",))
                    .select_related("user")
                    .get(
                        pk=ticket.pk,
                        user_id=user.pk,
                        category_id=category.pk,
                    )
                )
            except Ticket.DoesNotExist as error:
                raise TicketNotFoundError from error

            current_ticket.category = category

            if not current_ticket.is_valid_for_entry_at(
                request_time
            ):
                raise TicketPdfUnavailableError

            current_source = build_ticket_pdf_source(
                current_ticket
            )
            current_hash = ticket_pdf_source_hash(current_source)

            if (
                current_ticket.pdf_storage_name
                and current_ticket.pdf_source_hash == current_hash
                and storage.exists(
                    current_ticket.pdf_storage_name
                )
            ):
                return TicketPdfResult(
                    ticket=current_ticket,
                    storage_name=(
                        current_ticket.pdf_storage_name
                    ),
                    generated=False,
                )

            if (
                current_hash == preliminary_hash
                and preliminary_pdf is not None
            ):
                pdf_bytes = preliminary_pdf
            else:
                pdf_bytes = render_ticket_pdf(current_source)

            previous_storage_name = (
                current_ticket.pdf_storage_name
            )
            requested_name = (
                f"tickets/{current_ticket.pk}/"
                f"{uuid4().hex}.pdf"
            )
            new_storage_name = storage.save(
                requested_name,
                ContentFile(pdf_bytes),
            )
            current_ticket.pdf_storage_name = new_storage_name
            current_ticket.pdf_source_hash = current_hash
            current_ticket.pdf_generated_at = timezone.now()
            current_ticket.save(
                update_fields=(
                    "pdf_storage_name",
                    "pdf_source_hash",
                    "pdf_generated_at",
                )
            )

            if (
                previous_storage_name
                and previous_storage_name != new_storage_name
            ):
                transaction.on_commit(
                    partial(
                        delete_ticket_pdf,
                        previous_storage_name,
                    ),
                    robust=True,
                )

            return TicketPdfResult(
                ticket=current_ticket,
                storage_name=new_storage_name,
                generated=True,
            )
    except (
        AuthenticationRequiredError,
        TicketNotFoundError,
        TicketPdfUnavailableError,
    ):
        if new_storage_name:
            storage.delete(new_storage_name)
        raise
    except Exception as error:
        if new_storage_name:
            storage.delete(new_storage_name)
        raise TicketPdfGenerationError from error
