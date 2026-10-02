from django.urls import path

from . import views
from .common_views import audit, health

urlpatterns = [
    path("", views.dashboard),
    path("action/", views.browser_action),
    path("audit/", audit),
    path("health/", health),
    path("api/v1/actions/", views.api_submit),
    path("api/v1/actions/<uuid:action_id>/", views.api_action),
    path("api/v1/actions/<uuid:action_id>/<str:command>/", views.api_action),
]
