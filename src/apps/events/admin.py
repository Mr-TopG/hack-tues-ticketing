from django.contrib import admin

from .models import Event, TicketCategory


class TicketCategoryInline(admin.TabularInline):
    model = TicketCategory
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


@admin.register(TicketCategory)
class TicketCategoryAdmin(admin.ModelAdmin):
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
