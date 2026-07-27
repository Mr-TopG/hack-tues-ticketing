from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch
from django.views.decorators.http import require_http_methods
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from apps.accounts.models import OrganizerProfile

from .forms import OrganizerEventForm, TicketCategoryFormSet
from .models import Event, TicketCategory


PUBLIC_EVENT_STATUSES = (
    Event.Status.PUBLISHED,
    Event.Status.CANCELLED,
    Event.Status.COMPLETED,
)


def public_event_queryset():
    active_categories = TicketCategory.objects.filter(
        is_active=True,
    ).order_by(
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
    event = get_object_or_404(
        public_event_queryset(),
        slug=slug,
    )

    return render(
        request,
        "events/event_detail.html",
        {
            "event": event,
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
                form.save()
                formset.save()

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
        event.delete()

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

