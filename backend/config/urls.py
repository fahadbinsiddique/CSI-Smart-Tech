"""
URL configuration for Factory Traffic Management System.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('traffic.api.urls')),
]

