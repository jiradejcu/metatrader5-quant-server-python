from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TradeViewSet, SendMarketOrderView, ModifySLTPView, PriceAlertView

router = DefaultRouter()
router.register(r'trades', TradeViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('send_market_order/', SendMarketOrderView.as_view(), name='send_market_order'),
    path('modify_sl_tp/', ModifySLTPView.as_view(), name='modify_sl_tp'),
    path('price_alert/', PriceAlertView.as_view(), name='price_alert'),
]