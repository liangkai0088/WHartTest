from django.urls import path

from .consumers import ExecutionDashboardConsumer

websocket_urlpatterns = [
    path("ws/execution/dashboard/", ExecutionDashboardConsumer.as_asgi()),
]
