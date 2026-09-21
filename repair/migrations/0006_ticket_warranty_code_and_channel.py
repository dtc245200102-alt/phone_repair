from django.db import migrations, models


def backfill_codes(apps, schema_editor):
    RepairTicket = apps.get_model("repair", "RepairTicket")
    Warranty = apps.get_model("repair", "Warranty")

    for ticket in RepairTicket.objects.filter(code__isnull=True):
        timestamp = ticket.created_at.strftime("%y%m") if ticket.created_at else "0000"
        ticket.code = f"SC{timestamp}{ticket.pk:05d}"
        ticket.save(update_fields=["code"])

    for warranty in Warranty.objects.filter(code__isnull=True):
        timestamp = warranty.start_date.strftime("%y%m") if warranty.start_date else "0000"
        warranty.code = f"BH{timestamp}{warranty.pk:05d}"
        warranty.save(update_fields=["code"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("repair", "0005_alter_part_options_customer_user_part_category_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="repairticket",
            name="code",
            field=models.CharField(
                blank=True, null=True, unique=True, max_length=20,
                verbose_name="Mã phiếu sửa chữa",
                help_text="Tự sinh khi lưu, ví dụ SC260900123. Dùng mã này để tra cứu/tìm kiếm.",
            ),
        ),
        migrations.AddField(
            model_name="repairticket",
            name="received_channel",
            field=models.CharField(
                choices=[("ONLINE", "Khách tự đặt lịch online"), ("WALK_IN", "Lễ tân tiếp nhận trực tiếp")],
                default="WALK_IN", max_length=20, verbose_name="Kênh tiếp nhận",
            ),
        ),
        migrations.AddField(
            model_name="repairticket",
            name="preferred_time",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Thời gian khách hẹn mang máy đến",
                help_text="Chỉ áp dụng khi khách tự đặt lịch online.",
            ),
        ),
        migrations.AddField(
            model_name="warranty",
            name="code",
            field=models.CharField(
                blank=True, null=True, unique=True, max_length=20,
                verbose_name="Mã bảo hành",
                help_text="Tự sinh khi lưu, ví dụ BH260900045. Cấp mã này cho khách để tra cứu.",
            ),
        ),
        migrations.RunPython(backfill_codes, noop_reverse),
    ]