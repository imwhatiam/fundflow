from django.urls import path

from fundflow.views import SectorIntradayView, SectorListView

urlpatterns = [
    path("sectors/", SectorListView.as_view(), name="sector-list"),
    path("sectors/intraday/", SectorIntradayView.as_view(), name="sector-intraday"),
]
