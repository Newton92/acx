from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cases", "0010_casecall_webrtc_signal"),
    ]

    operations = [
        migrations.AddField(
            model_name="casenote",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterModelOptions(
            name="casenote",
            options={"ordering": ["id"]},
        ),
    ]
