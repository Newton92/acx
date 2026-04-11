from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cases", "0009_casecall"),
    ]

    operations = [
        migrations.AddField(
            model_name="casecall",
            name="offer_sdp",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="casecall",
            name="answer_sdp",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="casecall",
            name="ice_initiator",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="casecall",
            name="ice_peer",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterModelOptions(
            name="casecall",
            options={"ordering": ["-created_at"]},
        ),
    ]
