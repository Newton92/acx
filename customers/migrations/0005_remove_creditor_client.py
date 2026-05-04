from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0004_creditor"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="creditor",
            name="client",
        ),
    ]
