from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0002_ticket_check_in_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="pdf_generated_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="pdf_source_hash",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="pdf_storage_name",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                max_length=500,
            ),
        ),
        migrations.AddConstraint(
            model_name="ticket",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        pdf_storage_name="",
                        pdf_source_hash="",
                        pdf_generated_at__isnull=True,
                    )
                    | (
                        ~models.Q(pdf_storage_name="")
                        & ~models.Q(pdf_source_hash="")
                        & models.Q(
                            pdf_generated_at__isnull=False,
                        )
                    )
                ),
                name="ticket_pdf_metadata_consistent",
            ),
        ),
    ]
