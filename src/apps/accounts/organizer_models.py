from django.conf import settings
from django.db import models


class OrganizerProfile(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organizer_profile",
    )

    organization_name = models.CharField(
        max_length=200,
        blank=True,
    )

    reason = models.TextField(
        help_text=(
            "Explain why you need permission to create "
            "and manage events."
        ),
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    requested_at = models.DateTimeField(auto_now_add=True)

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_organizer_requests",
    )

    class Meta:
        ordering = (
            "status",
            "-requested_at",
        )

    def __str__(self):
        return f"{self.user.email} — {self.get_status_display()}"

    @property
    def is_approved(self):
        return self.status == self.Status.APPROVED
