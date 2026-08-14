"""
执行进度看板 REST 视图。

认证与项目权限与项目内其他接口保持一致：
- JWT/APIKey 全局认证（DEFAULT_AUTHENTICATION_CLASSES）
- 显式 IsAuthenticated；项目成员校验逻辑镜像 testcases.permissions
"""
import logging

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from projects.models import ProjectMember
from testcases.models import TestExecution

from .models import ExecutionEventLog
from .serializers import ExecutionEventLogSerializer, RunSnapshotSerializer
from .services import compute_eta

logger = logging.getLogger(__name__)

# 事件列表最大条数（与协议一致）
EVENT_LIST_MAX_LIMIT = 500


def _get_run_for_user(request, run_id):
    """获取执行记录；非项目成员返回 None（超级管理员放行）。"""
    execution = get_object_or_404(TestExecution, id=run_id)
    user = request.user
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return execution
    is_member = ProjectMember.objects.filter(
        project_id=execution.suite.project_id,
        user=user,
        role__in=["owner", "admin", "member"],
    ).exists()
    return execution if is_member else None


def _denied():
    return Response({"detail": "您无权访问该执行记录"},
                    status=status.HTTP_403_FORBIDDEN)


class EventListView(APIView):
    """
    GET /api/execution-dashboard/runs/<run_id>/events/?after_id=&limit=500
    按 id 升序游标分页返回事件日志。
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, run_id):
        execution = _get_run_for_user(request, run_id)
        if execution is None:
            return _denied()

        queryset = ExecutionEventLog.objects.filter(run=execution)

        after_id = request.query_params.get("after_id")
        if after_id:
            try:
                after_id = int(after_id)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "after_id 必须是整数"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(id__gt=after_id)

        try:
            limit = int(request.query_params.get("limit", EVENT_LIST_MAX_LIMIT))
        except (TypeError, ValueError):
            limit = EVENT_LIST_MAX_LIMIT
        limit = max(1, min(limit, EVENT_LIST_MAX_LIMIT))

        events = list(queryset.order_by("id")[:limit])
        serializer = ExecutionEventLogSerializer(events, many=True)
        return Response(serializer.data)


class RunSnapshotView(APIView):
    """
    GET /api/execution-dashboard/runs/<run_id>/snapshot/
    返回 {run, nodes, eta} 完整快照。
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, run_id):
        execution = _get_run_for_user(request, run_id)
        if execution is None:
            return _denied()

        suite = execution.suite
        run_summary = {
            "id": execution.id,
            "project_id": suite.project_id,
            "suite_id": suite.id,
            "suite_name": suite.name,
            "status": execution.status,
            "executor_id": execution.executor_id,
            "executor_name": execution.executor.username if execution.executor else None,
            "total_count": execution.total_count,
            "passed_count": execution.passed_count,
            "failed_count": execution.failed_count,
            "skipped_count": execution.skipped_count,
            "error_count": execution.error_count,
            "pass_rate": execution.pass_rate,
            "started_at": execution.started_at,
            "completed_at": execution.completed_at,
            "duration": execution.duration,
            "created_at": execution.created_at,
        }

        nodes = [
            {
                "id": r.id,
                "testcase_id": r.testcase_id,
                "name": r.testcase.name,
                "status": r.status,
                "started_at": r.started_at,
                "completed_at": r.completed_at,
                "execution_time": r.execution_time,
                "error_message": r.error_message,
            }
            for r in execution.results.select_related("testcase").all()
        ]

        try:
            eta = compute_eta(execution)
        except Exception:
            logger.exception("计算 ETA 失败: run=%s", execution.id)
            eta = {"eta_seconds": 0.0, "remaining_seconds": 0.0,
                   "confidence": "low", "progress": 0.0}

        serializer = RunSnapshotSerializer(
            data={"run": run_summary, "nodes": nodes, "eta": eta}
        )
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
