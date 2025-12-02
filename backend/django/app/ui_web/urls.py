from django.urls import path
from . import views

urlpatterns = [
    path('', views.health_check_page, name = 'health_check_page')
]