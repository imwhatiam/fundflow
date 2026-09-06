from django.db import models
from django.utils import timezone


class KaipanlaSectorFundFlowSnapshot(models.Model):
    """开盘啦板块在某个 5 分钟刻度的当日累计资金流快照。

    开盘啦实时接口（RealRankingInfo）不提供板块指数、主力净占比及超大/大/中/小单
    拆分，因此这里只保存上游真实返回的字段，避免伪造缺失值。
    """

    sector_code = models.CharField(max_length=16, db_index=True, verbose_name="开盘啦板块代码")
    sector_name = models.CharField(max_length=64, verbose_name="开盘啦板块名称")
    trade_date = models.DateField(db_index=True, verbose_name="交易日")
    snapshot_time = models.DateTimeField(db_index=True, verbose_name="快照时间(已按5分钟对齐)")

    change_pct = models.DecimalField(
        max_digits=9, decimal_places=3, null=True, blank=True, verbose_name="涨跌幅(%)"
    )
    main_net_inflow = models.DecimalField(
        max_digits=18, decimal_places=2, verbose_name="主力净流入(元)"
    )
    main_buy = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True, verbose_name="主力买(元)"
    )
    main_sell = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True, verbose_name="主力卖(元)"
    )
    large_order_net_inflow = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True, verbose_name="300万以上大单净额(元)"
    )
    volume_ratio = models.DecimalField(
        max_digits=9, decimal_places=3, null=True, blank=True, verbose_name="量比"
    )
    turnover_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True, verbose_name="成交额(元)"
    )
    float_market_cap = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True, verbose_name="流通市值(元)"
    )
    total_market_cap = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True, verbose_name="总市值(元)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sector_code", "snapshot_time"],
                name="uniq_kaipanla_sector_snapshot_time",
            )
        ]
        indexes = [
            models.Index(fields=["sector_code", "trade_date"]),
            models.Index(fields=["trade_date", "snapshot_time"]),
        ]
        ordering = ["snapshot_time", "sector_code"]
        verbose_name = "开盘啦板块资金流快照"
        verbose_name_plural = verbose_name

    def __str__(self):
        local_time = timezone.localtime(self.snapshot_time)
        return f"{self.sector_code} {self.sector_name} @ {local_time:%Y-%m-%d %H:%M}"


class KaipanlaSectorFundFlowSnapshotStatus(models.Model):
    """一次开盘啦板块快照的抓取完整性状态。

    开盘啦通过单个 RealRankingInfo 接口分页拉取全量板块，没有东财那种流入/流出
    两份独立榜单，因此这里只记录单次抓取是否成功。
    """

    trade_date = models.DateField(db_index=True, verbose_name="交易日")
    snapshot_time = models.DateTimeField(db_index=True, verbose_name="快照时间")
    fetch_succeeded = models.BooleanField(verbose_name="抓取成功")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot_time"], name="uniq_kaipanla_sector_status_time"
            )
        ]
        ordering = ["snapshot_time"]
        verbose_name = "开盘啦板块资金流快照状态"
        verbose_name_plural = verbose_name

    def __str__(self):
        local_time = timezone.localtime(self.snapshot_time)
        return f"{local_time:%Y-%m-%d %H:%M} succeeded={self.fetch_succeeded}"
