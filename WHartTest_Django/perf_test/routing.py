"""性能测试 WebSocket 路由配置。"""

from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(
        r'ws/perf-test/(?P<execution_id>\d+)/$',
        consumers.PerfTestConsumer.as_asgi(),
    ),
]
