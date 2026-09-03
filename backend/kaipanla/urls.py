from django.urls import path

from kaipanla.views import KaipanlaSectorIntradayView, KaipanlaSectorListView

urlpatterns = [
    path("sectors/", KaipanlaSectorListView.as_view(), name="kaipanla-sector-list"),
    path("sectors/intraday/", KaipanlaSectorIntradayView.as_view(), name="kaipanla-sector-intraday"),
]
