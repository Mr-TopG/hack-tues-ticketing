import secrets

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.tickets.models


def populate_validation_tokens(apps, schema_editor):
    Ticket = apps.get_model("tickets", "Ticket")
    database_alias = schema_editor.connection.alias
    tickets = Ticket.objects.using(database_alias)

    for ticket_id in tickets.filter(
        validation_token__isnull=True,
    ).values_list("pk", flat=True).iterator():
        while True:
            token = secrets.token_urlsafe(32)

            if not tickets.filter(validation_token=token).exists():
                break

        tickets.filter(pk=ticket_id).update(
            validation_token=token,
        )


def ensure_checked_in_tickets_are_attributed(apps, schema_editor):
    Ticket = apps.get_model("tickets", "Ticket")
    database_alias = schema_editor.connection.alias

    if Ticket.objects.using(database_alias).filter(
        status="checked_in",
        checked_in_by__isnull=True,
    ).exists():
        raise RuntimeError(
            "Existing checked-in tickets must be attributed to "
            "their actual checker before this migration can continue."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="checked_in_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="checked_in_tickets",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="validation_token",
            field=models.CharField(
                editable=False,
                max_length=43,
                null=True,
            ),
        ),
        migrations.RunPython(
            populate_validation_tokens,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="ticket",
            name="validation_token",
            field=models.CharField(
                default=(
                    apps.tickets.models.generate_validation_token
                ),
                editable=False,
                max_length=43,
                unique=True,
            ),
        ),
        migrations.AlterModelOptions(
            name="ticket",
            options={
                "ordering": ("-issued_at",),
                "permissions": (
                    (
                        "check_in_ticket",
                        "Can check in tickets for any event",
                    ),
                ),
            },
        ),
        migrations.RemoveConstraint(
            model_name="ticket",
            name="ticket_status_timestamps_consistent",
        ),
        migrations.RunPython(
            ensure_checked_in_tickets_are_attributed,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="ticket",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        status="issued",
                        cancelled_at__isnull=True,
                        checked_in_at__isnull=True,
                        checked_in_by__isnull=True,
                    )
                    | models.Q(
                        status="cancelled",
                        cancelled_at__isnull=False,
                        checked_in_at__isnull=True,
                        checked_in_by__isnull=True,
                    )
                    | models.Q(
                        status="checked_in",
                        cancelled_at__isnull=True,
                        checked_in_at__isnull=False,
                        checked_in_by__isnull=False,
                    )
                ),
                name="ticket_status_timestamps_consistent",
            ),
        ),
    ]
