from secrets import token_urlsafe
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


def generate_validation_token():
    return token_urlsafe(32)


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

    validation_token = models.CharField(
        max_length=43,
        unique=True,
        default=generate_validation_token,
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
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="checked_in_tickets",
    )
    pdf_storage_name = models.CharField(
        max_length=500,
        blank=True,
        default="",
        editable=False,
    )
    pdf_source_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        editable=False,
    )
    pdf_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        ordering = ("-issued_at",)
        permissions = (
            (
                "check_in_ticket",
                "Can check in tickets for any event",
            ),
        )
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
                        checked_in_by__isnull=True,
                    )
                    | Q(
                        status="cancelled",
                        cancelled_at__isnull=False,
                        checked_in_at__isnull=True,
                        checked_in_by__isnull=True,
                    )
                    | Q(
                        status="checked_in",
                        cancelled_at__isnull=True,
                        checked_in_at__isnull=False,
                        checked_in_by__isnull=False,
                    )
                ),
                name="ticket_status_timestamps_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        pdf_storage_name="",
                        pdf_source_hash="",
                        pdf_generated_at__isnull=True,
                    )
                    | (
                        ~Q(pdf_storage_name="")
                        & ~Q(pdf_source_hash="")
                        & Q(pdf_generated_at__isnull=False)
                    )
                ),
                name="ticket_pdf_metadata_consistent",
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

    def is_valid_for_entry_at(self, moment=None):
        moment = moment or timezone.now()

        return (
            self.status == self.Status.ISSUED
            and self.category.event.status
            == self.category.event.Status.PUBLISHED
            and moment < self.category.event.ends_at
        )

    @property
    def is_valid_for_entry(self):
        return self.is_valid_for_entry_at()
