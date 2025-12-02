from django.contrib import admin
from django.urls import path, include

# Define path of this django server e.g. <Django-domain/admin, Django-domain/v1>
urlpatterns = [
    path('admin/', admin.site.urls),
    path('v1/', include('app.nexus.urls')),
    path('displays/', include('app.ui_web.urls'))
]