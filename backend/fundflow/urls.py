from django.urls import path

from fundflow.views import SectorListView, SectorIntradayView, StockIntradayView

urlpatterns = [
    path("sectors/", SectorListView.as_view(), name="sector-list"),
    path("sectors/intraday/", SectorIntradayView.as_view(), name="sector-intraday"),
    path("stocks/<str:code>/intraday/", StockIntradayView.as_view(), name="stock-intraday"),
]
