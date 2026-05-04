from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cases", "0012_case_creditor"),
    ]

    operations = [
        migrations.AddField(
            model_name="case",
            name="notify_customer",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="case",
            name="notify_creditor",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="case",
            name="notify_debtor",
            field=models.BooleanField(default=False),
        ),
    ]
