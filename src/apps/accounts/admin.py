from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("email",)

    list_display = (
        "email",
        "first_name",
        "last_name",
        "email_verified_at",
        "is_staff",
        "is_active",
    )

    search_fields = (
        "email",
        "first_name",
        "last_name",
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "email",
                    "password",
                ),
            },
        ),
        (
            "Personal information",
            {
                "fields": (
                    "first_name",
                    "last_name",
                ),
            },
        ),
        (
            "Email verification",
            {
                "fields": (
                    "email_verified_at",
                ),
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (
            "Important dates",
            {
                "fields": (
                    "last_login",
                    "date_joined",
                ),
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )


from django.utils import timezone

from .models import OrganizerProfile


@admin.register(OrganizerProfile)
class OrganizerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "organization_name",
        "status",
        "requested_at",
        "reviewed_at",
        "reviewed_by",
    )

    list_filter = (
        "status",
        "requested_at",
    )

    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
        "organization_name",
        "reason",
    )

    readonly_fields = (
        "requested_at",
        "reviewed_at",
        "reviewed_by",
    )

    actions = (
        "approve_requests",
        "reject_requests",
        "return_to_pending",
    )

    @admin.action(description="Approve selected organizer requests")
    def approve_requests(self, request, queryset):
        queryset.update(
            status=OrganizerProfile.Status.APPROVED,
            reviewed_at=timezone.now(),
            reviewed_by=request.user,
        )

    @admin.action(description="Reject selected organizer requests")
    def reject_requests(self, request, queryset):
        queryset.update(
            status=OrganizerProfile.Status.REJECTED,
            reviewed_at=timezone.now(),
            reviewed_by=request.user,
        )

    @admin.action(description="Return selected requests to pending")
    def return_to_pending(self, request, queryset):
        queryset.update(
            status=OrganizerProfile.Status.PENDING,
            reviewed_at=None,
            reviewed_by=None,
        )

    def save_model(self, request, obj, form, change):
        if obj.status == OrganizerProfile.Status.PENDING:
            obj.reviewed_at = None
            obj.reviewed_by = None
        else:
            obj.reviewed_at = timezone.now()
            obj.reviewed_by = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )
