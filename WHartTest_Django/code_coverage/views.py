import logging

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.response import Response

from projects.models import Project
from wharttest_django.pagination import StandardPagination
from wharttest_django.viewsets import BaseModelViewSet

from .models import CoverageReport, CoverageFile
from .serializers import (
    CoverageReportSerializer,
    CoverageUploadSerializer,
    CoverageFileSerializer,
)
from .services import parse_coverage_report

logger = logging.getLogger(__name__)


class CoverageReportViewSet(BaseModelViewSet):
    """覆盖率报告视图集"""

    queryset = CoverageReport.objects.all()
    serializer_class = CoverageReportSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['project', 'format', 'test_type', 'status']
    search_fields = ['name', 'test_execution_ref', 'git_commit']
    ordering_fields = ['created_at']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return CoverageUploadSerializer
        return CoverageReportSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return CoverageReport.objects.all()
        return CoverageReport.objects.filter(
            project__members__user=user
        ).distinct()

    def create(self, request, *args, **kwargs):
        upload_serializer = CoverageUploadSerializer(data=request.data)
        upload_serializer.is_valid(raise_exception=True)
        data = upload_serializer.validated_data

        project = self._resolve_project(data['project_id'], request)
        if project is None:
            return Response(
                {'error': '项目不存在或无权访问'},
                status=status.HTTP_403_FORBIDDEN,
            )

        report = CoverageReport.objects.create(
            project=project,
            name=data['name'],
            format=data['format'],
            test_type=data.get('test_type', 'api'),
            test_execution_ref=data.get('test_execution_ref'),
            git_commit=data.get('git_commit'),
            status='processing',
            uploader=request.user,
        )

        try:
            content = data['file'].read().decode('utf-8', errors='ignore')
            summary, files = parse_coverage_report(content, data['format'])
        except Exception as e:
            logger.error(f"解析覆盖率报告失败: {e}")
            report.status = 'failed'
            report.error_message = str(e)
            report.save(update_fields=['status', 'error_message'])
            return Response(
                {'error': f'解析失败: {e}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        report.summary = summary
        report.status = 'completed'
        report.save(update_fields=['summary', 'status'])

        CoverageFile.objects.bulk_create(
            [CoverageFile(report=report, **f) for f in files]
        )

        return Response(
            CoverageReportSerializer(report).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'])
    def files(self, request, pk=None):
        """获取报告的文件级覆盖率明细"""
        report = self.get_object()
        files = report.files.all()
        page = self.paginate_queryset(files)
        if page is not None:
            serializer = CoverageFileSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(CoverageFileSerializer(files, many=True).data)

    @staticmethod
    def _resolve_project(project_id, request):
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            return None
        if request.user.is_superuser:
            return project
        if project.members.filter(user=request.user).exists():
            return project
        return None
