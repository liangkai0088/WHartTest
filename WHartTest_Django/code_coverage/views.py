import logging

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.response import Response

from projects.models import Project
from wharttest_django.pagination import StandardPagination
from wharttest_django.viewsets import BaseModelViewSet

from .models import CoverageReport, CoverageFile, CoverageDelta, CoverageGateConfig
from .serializers import (
    CoverageReportSerializer,
    CoverageUploadSerializer,
    CoverageFileSerializer,
    CoverageDeltaSerializer,
    CoverageGateConfigSerializer,
)
from .services import parse_coverage_report, build_delta_for_reports

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

    @action(detail=True, methods=['post'])
    def generate_delta(self, request, pk=None):
        """基于基线报告生成本报告的增量覆盖率"""
        report = self.get_object()
        base_report_id = request.data.get('base_report_id')
        if not base_report_id:
            return Response(
                {'error': 'base_report_id 参数必填'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            base_report = CoverageReport.objects.get(id=base_report_id)
        except CoverageReport.DoesNotExist:
            return Response(
                {'error': '基线报告不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if base_report.project_id != report.project_id:
            return Response(
                {'error': '基线报告与当前报告不属于同一项目'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        summary, files = build_delta_for_reports(base_report, report)
        delta = CoverageDelta.objects.create(
            project=report.project,
            report=report,
            base_report=base_report,
            git_commit=report.git_commit or '',
            base_commit=base_report.git_commit,
            summary=summary,
            files=files,
            uploader=request.user,
        )
        return Response(
            CoverageDeltaSerializer(delta).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'])
    def check_gate(self, request, pk=None):
        """对本报告执行覆盖率门禁检查，返回是否通过阈值。"""
        report = self.get_object()
        gate = CoverageGateConfig.objects.filter(project_id=report.project_id).first()
        if gate is None:
            return Response({
                'enabled': False,
                'threshold': None,
                'actual_line_coverage': report.summary.get('line_coverage') if report.summary else None,
                'passed': None,
            })
        actual = report.summary.get('line_coverage') if report.summary else 0
        return Response(gate.evaluate(actual))

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


class CoverageDeltaViewSet(BaseModelViewSet):
    """增量覆盖率视图集（只读）"""

    queryset = CoverageDelta.objects.all()
    serializer_class = CoverageDeltaSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['project', 'git_commit', 'base_commit']
    search_fields = ['git_commit', 'base_commit']
    ordering_fields = ['created_at']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return CoverageDelta.objects.all()
        return CoverageDelta.objects.filter(
            project__members__user=user
        ).distinct()


class CoverageGateConfigViewSet(BaseModelViewSet):
    """覆盖率门禁配置视图集：按项目读取，可更新阈值与开关。"""

    queryset = CoverageGateConfig.objects.select_related('project')
    serializer_class = CoverageGateConfigSerializer
    pagination_class = None
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['project']

    @action(detail=False, methods=['get'])
    def by_project(self, request):
        """按项目返回门禁配置，不存在则按默认创建后返回。"""
        project_id = request.query_params.get('project')
        if not project_id:
            return Response({'error': 'project 参数必填'}, status=status.HTTP_400_BAD_REQUEST)
        gate, _ = CoverageGateConfig.objects.get_or_create(
            project_id=project_id, defaults={'enabled': False, 'min_line_coverage': 80.0}
        )
        return Response(CoverageGateConfigSerializer(gate).data)
