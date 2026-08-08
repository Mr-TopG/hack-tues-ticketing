import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("events", "0004_ticketcategory_category_per_user_limit_at_least_one"),
        ("tickets", "0004_ticket_email_delivery"),
    ]

    operations = [
        migrations.CreateModel(
            name="TicketRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "public_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        unique=True,
                    ),
                ),
                (
                    "idempotency_key",
                    models.UUIDField(
                        editable=False,
                        unique=True,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("succeeded", "Succeeded"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "failure_code",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=80,
                    ),
                ),
                (
                    "failure_message",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=300,
                    ),
                ),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                (
                    "completed_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ticket_requests",
                        to="events.ticketcategory",
                    ),
                ),
                (
                    "ticket",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="request",
                        to="tickets.ticket",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ticket_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("id",),
                "indexes": [
                    models.Index(
                        fields=["category", "status", "id"],
                        name="ticket_request_queue_idx",
                    ),
                    models.Index(
                        fields=["status", "id"],
                        name="ticket_request_status_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                status="pending",
                                ticket__isnull=True,
                                failure_code="",
                                failure_message="",
                                completed_at__isnull=True,
                            )
                            | models.Q(
                                status="succeeded",
                                ticket__isnull=False,
                                failure_code="",
                                failure_message="",
                                completed_at__isnull=False,
                            )
                            | (
                                models.Q(
                                    status="rejected",
                                    ticket__isnull=True,
                                    completed_at__isnull=False,
                                )
                                & ~models.Q(failure_code="")
                                & ~models.Q(failure_message="")
                            )
                        ),
                        name="ticket_request_state_consistent",
                    ),
                ],
            },
        ),
    ]
