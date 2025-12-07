from django.urls import path
from . import views

urlpatterns = [
    path('', views.health_check_page, name = 'health_check_page'),
    path('pause/', views.handle_pause_position_sync, name= 'pause_position_sync')
    path('summary/', views.get_arbitrage_summary, name= 'get_arbitrage_summary')
]