from functools import wraps
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import (
    Count,
    IntegerField,
    Prefetch,
    Q,
    Value,
)
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from apps.accounts.models import OrganizerProfile
from apps.accounts.verification import is_user_email_verified
from apps.tickets.forms import TicketIssueForm
from apps.tickets.models import Ticket

from .forms import OrganizerEventForm, TicketCategoryFormSet
from .models import Event, TicketCategory


PUBLIC_EVENT_STATUSES = (
    Event.Status.PUBLISHED,
    Event.Status.CANCELLED,
    Event.Status.COMPLETED,
)


def public_event_queryset(*, ticket_user=None):
    active_categories = TicketCategory.objects.filter(
        is_active=True,
    )

    if ticket_user is not None:
        active_categories = active_categories.annotate(
            active_ticket_count=Count(
                "tickets",
                filter=Q(
                    tickets__status__in=Ticket.ACTIVE_STATUSES,
                ),
            ),
            user_active_ticket_count=Count(
                "tickets",
                filter=Q(
                    tickets__status__in=Ticket.ACTIVE_STATUSES,
                    tickets__user=ticket_user,
                ),
            ),
        )
    else:
        active_categories = active_categories.annotate(
            active_ticket_count=Count(
                "tickets",
                filter=Q(
                    tickets__status__in=Ticket.ACTIVE_STATUSES,
                ),
            ),
            user_active_ticket_count=Value(
                0,
                output_field=IntegerField(),
            ),
        )

    active_categories = active_categories.order_by(
        "sort_order",
        "name",
    )

    return Event.objects.filter(
        status__in=PUBLIC_EVENT_STATUSES,
    ).prefetch_related(
        Prefetch(
            "ticket_categories",
            queryset=active_categories,
            to_attr="public_ticket_categories",
        )
    )


def event_list(request):
    events = public_event_queryset()

    return render(
        request,
        "events/event_list.html",
        {
            "events": events,
        },
    )


def event_detail(request, slug):
    ticket_user = (
        request.user
        if request.user.is_authenticated
        else None
    )

    event = get_object_or_404(
        public_event_queryset(ticket_user=ticket_user),
        slug=slug,
    )

    request_time = timezone.now()
    event.display_registration_state = event.registration_state_at(
        request_time
    )
    email_verified = is_user_email_verified(request.user)

    for category in event.public_ticket_categories:
        category.display_registration_state = (
            category.registration_state_at(request_time)
        )
        category.remaining_capacity = max(
            category.capacity - category.active_ticket_count,
            0,
        )
        category.issue_form = None

        if category.display_registration_state == "upcoming":
            category.ticket_action = "upcoming"
        elif category.display_registration_state != "open":
            category.ticket_action = "closed"
        elif category.remaining_capacity == 0:
            category.ticket_action = "sold_out"
        elif not request.user.is_authenticated:
            category.ticket_action = "login"
        elif not email_verified:
            category.ticket_action = "verify"
        elif (
            category.user_active_ticket_count
            >= category.per_user_limit
        ):
            category.ticket_action = "limit_reached"
        else:
            category.ticket_action = "issue"
            category.issue_form = TicketIssueForm(
                auto_id=f"id_category_{category.pk}_%s",
                initial={
                    "idempotency_key": uuid4(),
                }
            )

    return render(
        request,
        "events/event_detail.html",
        {
            "event": event,
            "email_verified": email_verified,
        },
    )


def approved_organizer_required(view_function):
    @wraps(view_function)
    @login_required
    def wrapper(request, *args, **kwargs):
        approved = OrganizerProfile.objects.filter(
            user=request.user,
            status=OrganizerProfile.Status.APPROVED,
        ).exists()

        if not approved:
            messages.error(
                request,
                "Your account is not approved as an organizer.",
            )

            return redirect("accounts:organizer_request")

        return view_function(
            request,
            *args,
            **kwargs,
        )

    return wrapper


@approved_organizer_required
def organizer_event_list(request):
    events = Event.objects.filter(
        organizer=request.user,
    ).prefetch_related(
        "ticket_categories"
    ).order_by(
        "-created_at"
    )

    return render(
        request,
        "events/manage/event_list.html",
        {
            "events": events,
        },
    )


@approved_organizer_required
def organizer_event_create(request):
    event = Event(
        organizer=request.user,
        status=Event.Status.DRAFT,
    )

    if request.method == "POST":
        form = OrganizerEventForm(
            request.POST,
            instance=event,
        )

        formset = TicketCategoryFormSet(
            request.POST,
            instance=event,
            prefix="categories",
        )

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                saved_event = form.save(commit=False)
                saved_event.organizer = request.user
                saved_event.status = Event.Status.DRAFT
                saved_event.save()

                formset.instance = saved_event
                formset.save()

            messages.success(
                request,
                "The event was created as a draft.",
            )

            return redirect("events_manage:list")
    else:
        form = OrganizerEventForm(instance=event)

        formset = TicketCategoryFormSet(
            instance=event,
            prefix="categories",
        )

    return render(
        request,
        "events/manage/event_form.html",
        {
            "event": event,
            "form": form,
            "formset": formset,
            "page_title": "Create event",
        },
    )


@approved_organizer_required
def organizer_event_update(request, pk):
    event = get_object_or_404(
        Event,
        pk=pk,
        organizer=request.user,
    )

    if request.method == "POST":
        saved = False

        with transaction.atomic():
            list(
                TicketCategory.objects.select_for_update(
                    of=("self",)
                )
                .filter(event=event)
                .order_by("pk")
                .values_list("pk", flat=True)
            )

            event = get_object_or_404(
                Event.objects.select_for_update(),
                pk=event.pk,
                organizer=request.user,
            )

            form = OrganizerEventForm(
                request.POST,
                instance=event,
            )

            formset = TicketCategoryFormSet(
                request.POST,
                instance=event,
                prefix="categories",
            )

            if form.is_valid() and formset.is_valid():
                form.save()
                formset.save()
                saved = True

        if saved:
            messages.success(
                request,
                "The event was updated.",
            )

            return redirect("events_manage:list")
    else:
        form = OrganizerEventForm(instance=event)

        formset = TicketCategoryFormSet(
            instance=event,
            prefix="categories",
        )

    return render(
        request,
        "events/manage/event_form.html",
        {
            "event": event,
            "form": form,
            "formset": formset,
            "page_title": "Edit event",
        },
    )


@approved_organizer_required
@require_http_methods(["GET", "POST"])
def organizer_event_publish(request, pk):
    event = get_object_or_404(
        Event,
        pk=pk,
        organizer=request.user,
    )

    if event.status != Event.Status.DRAFT:
        messages.error(
            request,
            "Only draft events can be published.",
        )

        return redirect("events_manage:list")

    if request.method == "POST":
        with transaction.atomic():
            list(
                TicketCategory.objects.select_for_update(
                    of=("self",)
                )
                .filter(event=event)
                .order_by("pk")
                .values_list("pk", flat=True)
            )

            event = get_object_or_404(
                Event.objects.select_for_update(),
                pk=event.pk,
                organizer=request.user,
            )

            if event.status != Event.Status.DRAFT:
                messages.error(
                    request,
                    "Only draft events can be published.",
                )

                return redirect("events_manage:list")

            event.status = Event.Status.PUBLISHED
            event.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

        messages.success(
            request,
            f"{event.name} is now published.",
        )

        return redirect("events_manage:list")

    return render(
        request,
        "events/manage/event_confirm_action.html",
        {
            "event": event,
            "page_title": "Publish event",
            "action_name": "Publish event",
            "action_class": "button",
            "action_description": (
                "The event will become publicly visible. "
                "Ticket registration will follow the configured "
                "event and category registration windows."
            ),
        },
    )


@approved_organizer_required
@require_http_methods(["GET", "POST"])
def organizer_event_cancel(request, pk):
    event = get_object_or_404(
        Event,
        pk=pk,
        organizer=request.user,
    )

    if event.status != Event.Status.PUBLISHED:
        messages.error(
            request,
            "Only published events can be cancelled.",
        )

        return redirect("events_manage:list")

    if request.method == "POST":
        with transaction.atomic():
            list(
                TicketCategory.objects.select_for_update(
                    of=("self",)
                )
                .filter(event=event)
                .order_by("pk")
                .values_list("pk", flat=True)
            )

            event = get_object_or_404(
                Event.objects.select_for_update(),
                pk=event.pk,
                organizer=request.user,
            )

            if event.status != Event.Status.PUBLISHED:
                messages.error(
                    request,
                    "Only published events can be cancelled.",
                )

                return redirect("events_manage:list")

            event.status = Event.Status.CANCELLED
            event.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

        messages.success(
            request,
            f"{event.name} has been cancelled.",
        )

        return redirect("events_manage:list")

    return render(
        request,
        "events/manage/event_confirm_action.html",
        {
            "event": event,
            "page_title": "Cancel event",
            "action_name": "Cancel event",
            "action_class": "button-warning",
            "action_description": (
                "The public event page will remain visible, "
                "but registration will be closed."
            ),
        },
    )


@approved_organizer_required
@require_http_methods(["GET", "POST"])
def organizer_event_delete(request, pk):
    event = get_object_or_404(
        Event,
        pk=pk,
        organizer=request.user,
    )

    if event.status != Event.Status.DRAFT:
        messages.error(
            request,
            "Only draft events can be permanently deleted. "
            "Published events must be cancelled instead.",
        )

        return redirect("events_manage:list")

    if request.method == "POST":
        event_name = event.name

        try:
            with transaction.atomic():
                event.delete()
        except ProtectedError:
            messages.error(
                request,
                "An event with ticket history cannot be deleted.",
            )
            return redirect("events_manage:list")

        messages.success(
            request,
            f"{event_name} was permanently deleted.",
        )

        return redirect("events_manage:list")

    return render(
        request,
        "events/manage/event_confirm_action.html",
        {
            "event": event,
            "page_title": "Delete draft",
            "action_name": "Permanently delete draft",
            "action_class": "button-danger",
            "action_description": (
                "The event and all its ticket categories "
                "will be permanently removed."
            ),
        },
    )
