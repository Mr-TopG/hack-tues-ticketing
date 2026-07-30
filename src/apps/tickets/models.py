from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Ticket(models.Model):
    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        CANCELLED = "cancelled", "Cancelled"
        CHECKED_IN = "checked_in", "Checked in"

    ACTIVE_STATUSES = (
        Status.ISSUED,
        Status.CHECKED_IN,
    )

    id = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tickets",
    )

    category = models.ForeignKey(
        "events.TicketCategory",
        on_delete=models.PROTECT,
        related_name="tickets",
    )

    idempotency_key = models.UUIDField(
        unique=True,
        editable=False,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ISSUED,
        db_index=True,
    )

    issued_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    checked_in_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("-issued_at",)
        indexes = [
            models.Index(
                fields=("category", "status"),
                name="ticket_category_status_idx",
            ),
            models.Index(
                fields=("user", "status"),
                name="ticket_user_status_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        status="issued",
                        cancelled_at__isnull=True,
                        checked_in_at__isnull=True,
                    )
                    | Q(
                        status="cancelled",
                        cancelled_at__isnull=False,
                        checked_in_at__isnull=True,
                    )
                    | Q(
                        status="checked_in",
                        cancelled_at__isnull=True,
                        checked_in_at__isnull=False,
                    )
                ),
                name="ticket_status_timestamps_consistent",
            ),
        ]

    def __str__(self):
        return f"{self.category} — {self.user}"

    @property
    def event(self):
        return self.category.event

    @property
    def counts_against_capacity(self):
        return self.status in self.ACTIVE_STATUSES

    def can_be_cancelled_at(self, moment=None):
        moment = moment or timezone.now()

        return (
            self.status == self.Status.ISSUED
            and moment < self.category.event.starts_at
        )

    @property
    def can_be_cancelled(self):
        return self.can_be_cancelled_at()
