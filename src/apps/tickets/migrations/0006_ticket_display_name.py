from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0005_ticket_request"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="display_name",
            field=models.CharField(
                blank=True,
                default="",
                max_length=80,
            ),
        ),
    ]
