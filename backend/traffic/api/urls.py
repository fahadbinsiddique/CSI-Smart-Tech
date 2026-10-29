"""
URL routing for the Traffic Management System API.
Supports both with and without trailing slashes.
"""
from django.urls import re_path
from traffic.api import views

urlpatterns = [
    # Health
    re_path(r'^health/?$', views.health_check, name='health-check'),

    # Junctions
    re_path(r'^junctions/?$', views.junction_list, name='junction-list'),
    re_path(r'^junctions/(?P<junction_id>[^/]+)/?$', views.junction_detail, name='junction-detail'),
    re_path(r'^junctions/(?P<junction_id>[^/]+)/status/?$', views.junction_status, name='junction-status'),
    re_path(r'^junctions/(?P<junction_id>[^/]+)/commands/?$', views.junction_commands, name='junction-commands'),
    re_path(r'^junctions/(?P<junction_id>[^/]+)/history/?$', views.junction_history, name='junction-history'),

    # Sensor Events
    re_path(r'^sensor-events/?$', views.sensor_events, name='sensor-events'),

    # Controller Events
    re_path(r'^controller-events/?$', views.controller_events, name='controller-events'),
]
