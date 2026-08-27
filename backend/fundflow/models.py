from django.db import models
from django.utils import timezone


class EastmoneySectorFundFlowSnapshot(models.Model):
    """东方财富行业板块在某个 15 分钟刻度的当日累计资金流快照。"""

    sector_code = models.CharField(max_length=16, db_index=True, verbose_name="东财板块代码")
    sector_name = models.CharField(max_length=64, verbose_name="东财板块名称")
    trade_date = models.DateField(db_index=True, verbose_name="交易日")
    snapshot_time = models.DateTimeField(db_index=True, verbose_name="快照时间(已按15分钟对齐)")

    latest_index = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True, verbose_name="板块指数"
    )
    change_pct = models.DecimalField(
        max_digits=7, decimal_places=3, null=True, blank=True, verbose_name="涨跌幅(%)"
    )
    main_net_inflow = models.DecimalField(
        max_digits=18, decimal_places=2, verbose_name="主力净流入(元)"
    )
    main_net_inflow_ratio = models.DecimalField(
        max_digits=7, decimal_places=3, null=True, blank=True, verbose_name="主力净占比(%)"
    )
    super_large_net_inflow = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True, verbose_name="超大单净流入(元)"
    )
    large_net_inflow = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True, verbose_name="大单净流入(元)"
    )
    medium_net_inflow = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True, verbose_name="中单净流入(元)"
    )
    small_net_inflow = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True, verbose_name="小单净流入(元)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sector_code", "snapshot_time"],
                name="uniq_eastmoney_sector_snapshot_time",
            )
        ]
        indexes = [
            models.Index(fields=["sector_code", "trade_date"]),
            models.Index(fields=["trade_date", "snapshot_time"]),
        ]
        ordering = ["snapshot_time", "sector_code"]
        verbose_name = "东财行业资金流快照"
        verbose_name_plural = verbose_name

    def __str__(self):
        local_time = timezone.localtime(self.snapshot_time)
        return f"{self.sector_code} {self.sector_name} @ {local_time:%Y-%m-%d %H:%M}"


class EastmoneySectorFundFlowSnapshotStatus(models.Model):
    """一次行业快照中流入、流出排行榜请求的完整性状态。"""

    trade_date = models.DateField(db_index=True, verbose_name="交易日")
    snapshot_time = models.DateTimeField(unique=True, db_index=True, verbose_name="快照时间")
    inflow_succeeded = models.BooleanField(verbose_name="流入榜请求成功")
    outflow_succeeded = models.BooleanField(verbose_name="流出榜请求成功")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["snapshot_time"]
        verbose_name = "东财行业资金流快照状态"
        verbose_name_plural = verbose_name

    def __str__(self):
        local_time = timezone.localtime(self.snapshot_time)
        return (
            f"{local_time:%Y-%m-%d %H:%M} "
            f"inflow={self.inflow_succeeded} outflow={self.outflow_succeeded}"
        )
