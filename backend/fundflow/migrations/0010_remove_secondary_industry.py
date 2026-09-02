from django.db import migrations, models


def remove_secondary_industry_rows(apps, schema_editor):
    snapshot = apps.get_model("fundflow", "EastmoneySectorFundFlowSnapshot")
    status = apps.get_model("fundflow", "EastmoneySectorFundFlowSnapshotStatus")
    snapshot.objects.filter(industry_level=2).delete()
    status.objects.filter(industry_level=2).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("fundflow", "0009_add_industry_level"),
    ]

    operations = [
        migrations.RunPython(remove_secondary_industry_rows, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="eastmoneysectorfundflowsnapshot",
            name="uniq_eastmoney_sector_level_snapshot_time",
        ),
        migrations.RemoveIndex(
            model_name="eastmoneysectorfundflowsnapshot",
            name="sector_level_code_date_idx",
        ),
        migrations.RemoveIndex(
            model_name="eastmoneysectorfundflowsnapshot",
            name="sector_level_date_time_idx",
        ),
        migrations.RemoveField(
            model_name="eastmoneysectorfundflowsnapshot",
            name="industry_level",
        ),
        migrations.AddConstraint(
            model_name="eastmoneysectorfundflowsnapshot",
            constraint=models.UniqueConstraint(
                fields=("sector_code", "snapshot_time"),
                name="uniq_eastmoney_sector_snapshot_time",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="eastmoneysectorfundflowsnapshotstatus",
            name="uniq_eastmoney_sector_level_status_time",
        ),
        migrations.RemoveField(
            model_name="eastmoneysectorfundflowsnapshotstatus",
            name="industry_level",
        ),
        migrations.AddConstraint(
            model_name="eastmoneysectorfundflowsnapshotstatus",
            constraint=models.UniqueConstraint(
                fields=("snapshot_time",), name="uniq_eastmoney_sector_status_time"
            ),
        ),
        migrations.AlterModelOptions(
            name="eastmoneysectorfundflowsnapshot",
            options={
                "ordering": ["snapshot_time", "sector_code"],
                "verbose_name": "东财三级行业资金流快照",
                "verbose_name_plural": "东财三级行业资金流快照",
            },
        ),
        migrations.AlterModelOptions(
            name="eastmoneysectorfundflowsnapshotstatus",
            options={
                "ordering": ["snapshot_time"],
                "verbose_name": "东财三级行业资金流快照状态",
                "verbose_name_plural": "东财三级行业资金流快照状态",
            },
        ),
    ]
