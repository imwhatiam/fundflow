from django.urls import path

from kaipanla.views import (
    KaipanlaSectorIntradayHistoryView,
    KaipanlaSectorIntradayView,
    KaipanlaSectorListView,
)

urlpatterns = [
    path("sectors/", KaipanlaSectorListView.as_view(), name="kaipanla-sector-list"),
    path("sectors/intraday/", KaipanlaSectorIntradayView.as_view(), name="kaipanla-sector-intraday"),
    path("sectors/intraday/history/", KaipanlaSectorIntradayHistoryView.as_view(), name="kaipanla-sector-intraday-history"),
]
