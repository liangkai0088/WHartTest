"""性能测试 WebSocket Consumer：向前端推送执行进度与实时指标。"""

import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

from .push import GROUP_PREFIX

logger = logging.getLogger(__name__)


class PerfTestConsumer(AsyncWebsocketConsumer):
    """前端连接 /ws/perf-test/<execution_id>/ 以订阅执行进度。"""

    async def connect(self):
        execution_id = self.scope['url_route']['kwargs'].get('execution_id')
        if not execution_id:
            await self.close()
            return
        self.group_name = f"{GROUP_PREFIX}{execution_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        group_name = getattr(self, 'group_name', None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def perf_test_update(self, event):
        await self.send(text_data=json.dumps(event.get('data', {})))
