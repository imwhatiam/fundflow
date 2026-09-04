from django.urls import path

from fundflow.views import SectorIntradayHistoryView, SectorIntradayView, SectorListView

urlpatterns = [
    path("sectors/", SectorListView.as_view(), name="sector-list"),
    path("sectors/intraday/", SectorIntradayView.as_view(), name="sector-intraday"),
    path("sectors/intraday/history/", SectorIntradayHistoryView.as_view(), name="sector-intraday-history"),
]
