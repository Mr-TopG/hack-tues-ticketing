from django.contrib import admin

from .models import Ticket


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "event_name",
        "category",
        "status",
        "issued_at",
        "cancelled_at",
        "checked_in_at",
        "checked_in_by",
    )

    list_filter = (
        "status",
        "category__event",
        "category",
    )

    search_fields = (
        "id",
        "user__email",
        "user__first_name",
        "user__last_name",
        "category__event__name",
        "category__name",
    )

    readonly_fields = (
        "id",
        "user",
        "category",
        "idempotency_key",
        "status",
        "issued_at",
        "cancelled_at",
        "checked_in_at",
        "checked_in_by",
    )

    list_select_related = (
        "user",
        "category__event",
        "checked_in_by",
    )

    ordering = ("-issued_at",)
    date_hierarchy = "issued_at"

    @admin.display(
        description="Event",
        ordering="category__event__name",
    )
    def event_name(self, ticket):
        return ticket.category.event.name

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
