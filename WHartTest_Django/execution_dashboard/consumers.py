"""
AI 执行进度看板 WebSocket Consumer。

端点: /ws/execution/dashboard/?project_id=N
- 通过 scope.user（会话/JWT 中间件注入）认证
- 必须是项目成员（owner/admin/member，超级管理员放行）
- 加入组 exec_dash_proj_{project_id}，接收扁平信封消息
"""
import json
import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from projects.models import ProjectMember

logger = logging.getLogger(__name__)


class ExecutionDashboardConsumer(AsyncWebsocketConsumer):
    """执行进度看板消费者：纯下行推送，忽略客户端消息。"""

    async def connect(self):
        self.project_id = self._parse_project_id()
        self.group_name = (
            f"exec_dash_proj_{self.project_id}" if self.project_id else None
        )

        if not self.project_id:
            logger.warning("exec_dashboard: 缺少 project_id 查询参数")
            await self.close(code=4400)
            return

        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            logger.warning("exec_dashboard: 未认证连接 (project=%s)", self.project_id)
            await self.close(code=4401)
            return

        if not await self._is_project_member(user, self.project_id):
            logger.warning(
                "exec_dashboard: 用户 %s 不是项目 %s 成员",
                getattr(user, "username", user.id),
                self.project_id,
            )
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(
            "exec_dashboard: 已连接 user=%s project=%s",
            getattr(user, "username", user.id),
            self.project_id,
        )

    async def disconnect(self, close_code):
        if getattr(self, "group_name", None):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info("exec_dashboard: 已断开 project=%s code=%s",
                    getattr(self, "project_id", None), close_code)

    async def receive(self, text_data=None, bytes_data=None):
        """纯下行通道，忽略客户端消息（可选 ping/echo，暂不处理）。"""

    async def exec_dash_event(self, event):
        """组消息分发入口（emit_execution_event 通过 group_send 触发）。"""
        await self.send(
            text_data=json.dumps(
                {
                    "event": event.get("event"),
                    "ts": event.get("ts"),
                    "data": event.get("data"),
                },
                ensure_ascii=False,
            )
        )

    def _parse_project_id(self):
        query_string = self.scope.get("query_string", b"").decode("utf-8")
        if not query_string:
            return None
        params = parse_qs(query_string)
        raw = params.get("project_id", [None])[0]
        if not raw or not raw.isdigit():
            return None
        return int(raw)

    @database_sync_to_async
    def _is_project_member(self, user, project_id):
        """项目成员校验（镜像 IsProjectMember* 权限类逻辑）。"""
        try:
            if getattr(user, "is_superuser", False):
                return True
            return ProjectMember.objects.filter(
                project_id=project_id,
                user=user,
                role__in=["owner", "admin", "member"],
            ).exists()
        except Exception:
            logger.exception(
                "exec_dashboard: 项目成员校验异常 user=%s project=%s",
                getattr(user, "id", None),
                project_id,
            )
            return False
