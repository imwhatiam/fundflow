from django.contrib import admin

from kaipanla.models import (
    KaipanlaSectorFundFlowSnapshot,
    KaipanlaSectorFundFlowSnapshotStatus,
)


@admin.register(KaipanlaSectorFundFlowSnapshot)
class KaipanlaSectorFundFlowSnapshotAdmin(admin.ModelAdmin):
    list_display = ("sector_code", "sector_name", "trade_date", "snapshot_time", "main_net_inflow")
    list_filter = ("trade_date",)
    search_fields = ("sector_code", "sector_name")


@admin.register(KaipanlaSectorFundFlowSnapshotStatus)
class KaipanlaSectorFundFlowSnapshotStatusAdmin(admin.ModelAdmin):
    list_display = ("trade_date", "snapshot_time", "fetch_succeeded")
    list_filter = ("trade_date", "fetch_succeeded")
