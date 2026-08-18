from django.db import models
from django.utils import timezone


class Sector(models.Model):
    """板块（行业/概念）基础信息，来自东财板块列表接口，低频同步（如每天一次）。"""

    CATEGORY_CHOICES = [
        ("industry", "行业板块"),
        ("concept", "概念板块"),
    ]

    code = models.CharField(max_length=16, unique=True, verbose_name="板块代码")  # 如 BK0490
    name = models.CharField(max_length=64, verbose_name="板块名称")               # 如 芯片
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]
        verbose_name = "板块"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"[{self.get_category_display()}] {self.name}({self.code})"


class SectorConstituent(models.Model):
    """板块-个股成分关系。一只股票可能属于多个概念板块，但通常只属于一个行业板块。"""

    sector = models.ForeignKey(Sector, related_name="constituents", on_delete=models.CASCADE)
    stock_code = models.CharField(max_length=10, db_index=True)
    stock_name = models.CharField(max_length=32, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sector", "stock_code"], name="uniq_sector_stock")
        ]
        indexes = [models.Index(fields=["stock_code"])]

    def __str__(self):
        return f"{self.sector.name} - {self.stock_code}"


class StockFundFlowSnapshot(models.Model):
    """
    单只个股在某个5分钟时间点的当日累计主力资金流快照。

    数据每5分钟由 `fetch_stock_fund_flow` management command 抓取一次并写入一行，
    整个交易日下来，每只股票会积累多行记录，前端据此可以画出"当天从开盘到现在"的
    分时累计曲线（等价于截图里的"当日走势"图，只是维度从板块下钻到了个股）。

    板块级别的曲线不单独存储，而是在 API 层实时用 SectorConstituent 关联查询这张表，
    按时间点分组求和得到（详见 fundflow/services/aggregation.py）。
    """

    MARKET_CHOICES = [
        ("SH", "上海"),
        ("SZ", "深圳"),
        ("BJ", "北京"),
        ("UNKNOWN", "未知"),
    ]

    stock_code = models.CharField(max_length=10, db_index=True, verbose_name="股票代码")
    stock_name = models.CharField(max_length=32, verbose_name="股票名称")
    market = models.CharField(max_length=8, choices=MARKET_CHOICES, verbose_name="交易所")

    trade_date = models.DateField(db_index=True, verbose_name="交易日")
    snapshot_time = models.DateTimeField(db_index=True, verbose_name="快照时间(已按5分钟对齐)")

    latest_price = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="最新价"
    )
    change_pct = models.DecimalField(
        max_digits=7, decimal_places=3, null=True, blank=True, verbose_name="涨跌幅(%)"
    )

    # 金额单位：元。前端展示时按需要再除以 1e8 转换成"亿元"，避免在数据库层做有损转换。
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
                fields=["stock_code", "snapshot_time"], name="uniq_stock_snapshot_time"
            )
        ]
        indexes = [
            models.Index(fields=["stock_code", "trade_date"]),
            models.Index(fields=["trade_date", "snapshot_time"]),
        ]
        ordering = ["snapshot_time"]
        verbose_name = "个股资金流快照"
        verbose_name_plural = verbose_name

    def __str__(self):
        local_time = timezone.localtime(self.snapshot_time)
        return f"{self.stock_code} {self.stock_name} @ {local_time:%Y-%m-%d %H:%M}"
