import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0003_ticket_pdf_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="TicketEmailDelivery",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "recipient",
                    models.EmailField(max_length=254),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sending", "Sending"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "message_token",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                    ),
                ),
                (
                    "attempt_count",
                    models.PositiveSmallIntegerField(default=0),
                ),
                (
                    "requested_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "last_attempt_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                    ),
                ),
                (
                    "sent_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                    ),
                ),
                (
                    "last_error",
                    models.TextField(
                        blank=True,
                        default="",
                    ),
                ),
                (
                    "ticket",
                    models.OneToOneField(
                        on_delete=(
                            django.db.models.deletion.CASCADE
                        ),
                        related_name="email_delivery",
                        to="tickets.ticket",
                    ),
                ),
            ],
            options={
                "ordering": ("-requested_at",),
                "indexes": [
                    models.Index(
                        fields=["status", "requested_at"],
                        name="ticket_email_status_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                status="pending",
                                sent_at__isnull=True,
                            )
                            | models.Q(
                                status="sending",
                                attempt_count__gte=1,
                                last_attempt_at__isnull=False,
                                sent_at__isnull=True,
                            )
                            | models.Q(
                                status="failed",
                                attempt_count__gte=1,
                                last_attempt_at__isnull=False,
                                sent_at__isnull=True,
                            )
                            | models.Q(
                                status="sent",
                                attempt_count__gte=1,
                                last_attempt_at__isnull=False,
                                sent_at__isnull=False,
                            )
                            | models.Q(
                                status="cancelled",
                                sent_at__isnull=True,
                            )
                        ),
                        name=(
                            "ticket_email_delivery_state_consistent"
                        ),
                    ),
                ],
            },
        ),
    ]
