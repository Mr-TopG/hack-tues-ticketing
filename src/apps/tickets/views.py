from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.events.models import TicketCategory

from .forms import TicketIssueForm
from .models import Ticket
from .services import (
    TicketCancellationError,
    TicketNotFoundError,
    TicketServiceError,
    cancel_ticket as cancel_ticket_service,
    issue_ticket as issue_ticket_service,
)


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
        .select_related("category__event")
        .order_by("-issued_at")
    )

    return render(
        request,
        "tickets/my_tickets.html",
        {
            "tickets": tickets,
        },
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
