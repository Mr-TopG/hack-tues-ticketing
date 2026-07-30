from django.contrib import admin

from .models import Ticket, TicketEmailDelivery


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
        "pdf_generated_at",
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
        "pdf_storage_name",
        "pdf_source_hash",
        "pdf_generated_at",
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


@admin.register(TicketEmailDelivery)
class TicketEmailDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ticket",
        "recipient",
        "status",
        "attempt_count",
        "requested_at",
        "last_attempt_at",
        "sent_at",
    )
    list_filter = ("status",)
    search_fields = (
        "id",
        "ticket__id",
        "recipient",
        "ticket__user__email",
        "ticket__category__event__name",
    )
    readonly_fields = (
        "id",
        "ticket",
        "recipient",
        "status",
        "message_token",
        "attempt_count",
        "requested_at",
        "last_attempt_at",
        "sent_at",
        "last_error",
    )
    list_select_related = (
        "ticket__user",
        "ticket__category__event",
    )
    ordering = ("-requested_at",)
    date_hierarchy = "requested_at"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
