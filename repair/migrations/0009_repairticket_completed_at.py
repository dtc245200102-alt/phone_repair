from django.db import migrations, models
from django.db.models import F


def backfill_completed_at(apps, schema_editor):
    RepairTicket = apps.get_model("repair", "RepairTicket")
    database = schema_editor.connection.alias
    RepairTicket.objects.using(database).filter(
        status__in=("DONE", "DELIVERED"),
        completed_at__isnull=True,
    ).update(completed_at=F("updated_at"))


def clear_completed_at(apps, schema_editor):
    RepairTicket = apps.get_model("repair", "RepairTicket")
    database = schema_editor.connection.alias
    RepairTicket.objects.using(database).update(completed_at=None)


class Migration(migrations.Migration):
    dependencies = [
        ("repair", "0008_adminaichatmessage"),
    ]

    operations = [
        migrations.AddField(
            model_name="repairticket",
            name="completed_at",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Được giữ nguyên khi chỉnh sửa phiếu sau khi hoàn thành."
                ),
                null=True,
                verbose_name="Thời điểm hoàn thành",
            ),
        ),
        migrations.RunPython(backfill_completed_at, clear_completed_at),
    ]
