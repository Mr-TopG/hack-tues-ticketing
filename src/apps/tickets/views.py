from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.storage import storages
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import (
    require_http_methods,
    require_POST,
    require_safe,
)

from apps.events.models import TicketCategory

from .delivery import (
    TicketEmailCooldownError,
    TicketEmailNotFoundError,
    TicketEmailRequestError,
    request_ticket_email,
)
from .forms import TicketCheckInLookupForm, TicketIssueForm
from .models import Ticket
from .pdf_service import (
    TicketPdfError,
    TicketPdfUnavailableError,
    get_or_generate_ticket_pdf,
)
from .qr import render_qr_svg, ticket_check_in_url
from .services import (
    TicketCancellationError,
    TicketCheckInError,
    TicketNotFoundError,
    TicketServiceError,
    get_ticket_for_check_in,
    user_can_access_ticket_check_in,
)
from .services import (
    cancel_ticket as cancel_ticket_service,
)
from .services import (
    check_in_ticket as check_in_ticket_service,
)
from .services import (
    issue_ticket as issue_ticket_service,
)


def _private_no_store(response):
    response.headers["Cache-Control"] = "private, no-store"
    # "no-referrer" serializes the Origin header as "null" for
    # form POSTs, which prevents Django from validating CSRF.
    response.headers["Referrer-Policy"] = "strict-origin"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@login_required
@require_POST
def issue_ticket(request, category_id):
    category = get_object_or_404(
        TicketCategory.objects.select_related("event"),
        pk=category_id,
    )
    event_url = category.event.get_absolute_url()
    form = TicketIssueForm(request.POST)

    if not form.is_valid():
        messages.error(
            request,
            "This ticket request is invalid. Please try again.",
        )
        return redirect(event_url)

    try:
        result = issue_ticket_service(
            user=request.user,
            category_id=category.pk,
            idempotency_key=form.cleaned_data["idempotency_key"],
        )
    except TicketCategory.DoesNotExist as error:
        raise Http404 from error
    except TicketServiceError as error:
        messages.error(request, str(error))
        return redirect(event_url)

    if result.created:
        messages.success(
            request,
            f"Your {category.name} ticket has been issued.",
        )
    else:
        messages.info(
            request,
            "This request was already processed. "
            "No duplicate ticket was created.",
        )

    return redirect("tickets:my_tickets")


@login_required
def my_tickets(request):
    tickets = (
        Ticket.objects.filter(user=request.user)
        .select_related(
            "category__event",
            "email_delivery",
        )
        .order_by("-issued_at")
    )

    return _private_no_store(
        render(
            request,
            "tickets/my_tickets.html",
            {
                "tickets": tickets,
            },
        )
    )


@login_required
@require_http_methods(["GET", "POST"])
def cancel_ticket(request, ticket_id):
    ticket = get_object_or_404(
        Ticket.objects.select_related("category__event"),
        pk=ticket_id,
        user=request.user,
    )

    if request.method == "POST":
        try:
            result = cancel_ticket_service(
                user=request.user,
                ticket_id=ticket.pk,
            )
        except TicketNotFoundError as error:
            raise Http404 from error
        except TicketCancellationError as error:
            messages.error(request, str(error))
        else:
            if result.cancelled:
                messages.success(
                    request,
                    "Your ticket has been cancelled.",
                )
            else:
                messages.info(
                    request,
                    "This ticket was already cancelled.",
                )

        return redirect("tickets:my_tickets")

    return render(
        request,
        "tickets/cancel_confirm.html",
        {
            "ticket": ticket,
        },
    )


@login_required
@require_safe
def ticket_qr(request, ticket_id):
    ticket = get_object_or_404(
        Ticket.objects.select_related("category__event"),
        pk=ticket_id,
        user=request.user,
        status=Ticket.Status.ISSUED,
        category__event__status="published",
        category__event__ends_at__gt=timezone.now(),
    )
    response = HttpResponse(
        render_qr_svg(
            ticket_check_in_url(ticket.validation_token)
        ),
        content_type="image/svg+xml",
    )
    response.headers["Content-Disposition"] = (
        f'inline; filename="ticket-{ticket.pk}.svg"'
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; sandbox"
    )
    return _private_no_store(response)


@login_required
@require_safe
def ticket_pdf(request, ticket_id):
    try:
        result = get_or_generate_ticket_pdf(
            user=request.user,
            ticket_id=ticket_id,
        )
    except TicketNotFoundError as error:
        raise Http404 from error
    except TicketPdfUnavailableError as error:
        messages.error(request, str(error))
        return redirect("tickets:my_tickets")
    except TicketPdfError as error:
        messages.error(request, str(error))
        return redirect("tickets:my_tickets")

    try:
        pdf_file = storages["ticket_pdfs"].open(
            result.storage_name,
            "rb",
        )
    except (OSError, ValueError):
        messages.error(
            request,
            "The ticket PDF could not be opened. Please try again.",
        )
        return redirect("tickets:my_tickets")

    response = FileResponse(
        pdf_file,
        as_attachment=True,
        filename=f"ticket-{result.ticket.pk}.pdf",
        content_type="application/pdf",
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return _private_no_store(response)


@login_required
@require_POST
def email_ticket(request, ticket_id):
    try:
        result = request_ticket_email(
            user=request.user,
            ticket_id=ticket_id,
        )
    except TicketEmailNotFoundError as error:
        raise Http404 from error
    except TicketEmailCooldownError as error:
        messages.warning(request, str(error))
    except TicketEmailRequestError as error:
        messages.error(request, str(error))
    else:
        if result.queued:
            messages.success(
                request,
                f"Your ticket was queued for delivery to "
                f"{result.delivery.recipient}.",
            )
        else:
            messages.info(
                request,
                "Your ticket email is already queued.",
            )

    return _private_no_store(
        redirect("tickets:my_tickets")
    )


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def check_in_lookup(request):
    if not user_can_access_ticket_check_in(request.user):
        raise PermissionDenied

    form = TicketCheckInLookupForm(
        request.POST or None,
    )

    if request.method == "POST" and form.is_valid():
        return _private_no_store(
            redirect(
                "tickets:check_in",
                validation_token=(
                    form.cleaned_data["validation_token"]
                ),
            )
        )

    return _private_no_store(
        render(
            request,
            "tickets/check_in_lookup.html",
            {
                "form": form,
            },
        )
    )


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def check_in_ticket(request, validation_token):
    try:
        ticket = get_ticket_for_check_in(
            user=request.user,
            validation_token=validation_token,
        )
    except TicketNotFoundError as error:
        raise Http404 from error

    if request.method == "POST":
        try:
            result = check_in_ticket_service(
                user=request.user,
                validation_token=validation_token,
            )
        except TicketNotFoundError as error:
            raise Http404 from error
        except TicketCheckInError as error:
            messages.error(request, str(error))
        else:
            messages.success(
                request,
                (
                    f"{result.ticket.user.email} was checked in "
                    f"for {result.ticket.category.event.name}."
                ),
            )

        return _private_no_store(
            redirect(
                "tickets:check_in",
                validation_token=validation_token,
            )
        )

    return _private_no_store(
        render(
            request,
            "tickets/check_in_confirm.html",
            {
                "ticket": ticket,
                "can_check_in": ticket.is_valid_for_entry,
            },
        )
    )
