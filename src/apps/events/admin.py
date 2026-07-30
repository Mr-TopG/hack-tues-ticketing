from django.contrib import admin
from django.db import transaction

from .forms import OrganizerTicketCategoryForm
from .models import Event, TicketCategory


class TicketCategoryInline(admin.TabularInline):
    model = TicketCategory
    form = OrganizerTicketCategoryForm
    extra = 0

    fields = (
        "name",
        "slug",
        "capacity",
        "per_user_limit",
        "is_active",
        "sort_order",
    )

    ordering = (
        "sort_order",
        "name",
    )


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organizer",
        "status",
        "starts_at",
        "registration_opens_at",
        "registration_closes_at",
    )

    list_filter = (
        "status",
        "starts_at",
    )

    search_fields = (
        "name",
        "venue",
        "description",
        "organizer__email",
        "organizer__first_name",
        "organizer__last_name",
    )

    autocomplete_fields = (
        "organizer",
    )

    prepopulated_fields = {
        "slug": ("name",),
    }

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    inlines = (
        TicketCategoryInline,
    )

    def changeform_view(
        self,
        request,
        object_id=None,
        form_url="",
        extra_context=None,
    ):
        if request.method == "POST" and object_id is not None:
            with transaction.atomic():
                list(
                    TicketCategory.objects.select_for_update(
                        of=("self",)
                    )
                    .filter(event_id=object_id)
                    .order_by("pk")
                    .values_list("pk", flat=True)
                )

                return super().changeform_view(
                    request,
                    object_id,
                    form_url,
                    extra_context,
                )

        return super().changeform_view(
            request,
            object_id,
            form_url,
            extra_context,
        )


@admin.register(TicketCategory)
class TicketCategoryAdmin(admin.ModelAdmin):
    def changeform_view(
        self,
        request,
        object_id=None,
        form_url="",
        extra_context=None,
    ):
        if request.method == "POST" and object_id is not None:
            with transaction.atomic():
                list(
                    TicketCategory.objects.select_for_update(
                        of=("self",)
                    )
                    .filter(pk=object_id)
                    .values_list("pk", flat=True)
                )

                return super().changeform_view(
                    request,
                    object_id,
                    form_url,
                    extra_context,
                )

        return super().changeform_view(
            request,
            object_id,
            form_url,
            extra_context,
        )

    list_display = (
        "name",
        "event",
        "capacity",
        "per_user_limit",
        "is_active",
        "sort_order",
    )

    list_filter = (
        "is_active",
        "event",
    )

    search_fields = (
        "name",
        "event__name",
        "event__organizer__email",
    )

    prepopulated_fields = {
        "slug": ("name",),
    }

    autocomplete_fields = (
        "event",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )
