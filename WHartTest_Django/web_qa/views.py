"""web_qa REST API 视图（嵌套于 /api/projects/{project_pk}/web-qa/）。"""

from __future__ import annotations

import logging
from pathlib import Path

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from projects.models import Project

from .models import AgentLocatorCache, QaBatchRun, QaRun, QaStepResult, QaSuite
from .permissions import IsWebQaProjectMember
from .runner import update_test_count
from .serializers import (
    AgentLocatorCacheSerializer,
    QaBatchRunSerializer,
    QaRunListSerializer,
    QaRunSerializer,
    QaStepResultSerializer,
    QaSuiteListSerializer,
    QaSuiteSerializer,
)
from .tasks import (
    generate_web_qa_suite_from_prd,
    run_web_qa_batch,
    run_web_qa_suite,
)

logger = logging.getLogger('web_qa')


def _err(message, code=400):
    return Response({'detail': message}, status=code)


class QaSuiteViewSet(viewsets.ModelViewSet):
    """Web QA 套件 CRUD + import/run/batch-run/prd-generate/locator-cache。"""

    serializer_class = QaSuiteSerializer
    permission_classes = [IsAuthenticated, IsWebQaProjectMember]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None

    def get_queryset(self):
        return QaSuite.objects.filter(project_id=self.kwargs.get('project_pk'))

    def get_project(self):
        return get_object_or_404(Project, pk=self.kwargs.get('project_pk'))

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        group = request.query_params.get('group')
        engine = request.query_params.get('engine')
        if group:
            qs = qs.filter(group=group)
        if engine:
            qs = qs.filter(engine=engine)
        qs = qs.select_related('llm_config')
        return Response(QaSuiteListSerializer(qs, many=True).data)

    def retrieve(self, request, *args, **kwargs):
        suite = self.get_object()
        return Response(QaSuiteSerializer(suite).data)

    def create(self, request, *args, **kwargs):
        project = self.get_project()
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        data['project'] = project.id

        llm_config_id = data.get('llm_config')
        if llm_config_id in ('', 'null', 'None'):
            data.pop('llm_config', None)
            llm_config_id = None

        serializer = QaSuiteSerializer(data=data)
        serializer.is_valid(raise_exception=True)

        suite = serializer.save(
            project=project,
            created_by=request.user,
            source='manual',
            status='draft',
            llm_config_id=llm_config_id,
        )
        update_test_count(suite)
        return Response(QaSuiteSerializer(suite).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        suite = self.get_object()
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        llm_config_id = data.pop('llm_config', None)
        if llm_config_id in ('', 'null', 'None'):
            llm_config_id = None
        serializer = QaSuiteSerializer(suite, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        suite = serializer.save(llm_config_id=llm_config_id)
        update_test_count(suite)
        return Response(QaSuiteSerializer(suite).data)

    def destroy(self, request, *args, **kwargs):
        suite = self.get_object()
        suite.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ---------- yaml 更新 ----------

    def update_yaml(self, request, project_pk=None, pk=None):
        suite = self.get_object()
        yaml_content = request.data.get('yaml_content')
        if yaml_content is None:
            return _err('缺少 yaml_content 字段', 400)
        suite.yaml_content = str(yaml_content)
        suite.status = 'draft' if suite.status != 'ready' else suite.status
        suite.save(update_fields=['yaml_content', 'status', 'updated_at'])
        update_test_count(suite)
        return Response(QaSuiteSerializer(suite).data)

    # ---------- 导入 ----------

    def import_suite(self, request, project_pk=None):
        """POST multipart {file, group?, engine?}。"""
        from .yaml_loader import count_tests

        project = self.get_project()
        file_obj = request.FILES.get('file')
        if not file_obj:
            return _err('缺少 file 字段（multipart yaml）', 400)
        name = (file_obj.name or '').lower()
        if not name.endswith(('.yaml', '.yml')):
            return _err('仅支持 .yaml / .yml 文件', 400)

        try:
            file_obj.seek(0)
            content = file_obj.read().decode('utf-8')
        except Exception as e:  # noqa: BLE001
            return _err(f'文件读取失败: {e}', 400)

        from .yaml_loader import parse_suite

        suite_info = parse_suite(content, tolerant=True)
        base_name = suite_info.name or Path(file_obj.name).stem
        if suite_info.errors and not suite_info.tests:
            return _err('YAML 解析失败: ' + '; '.join(suite_info.errors[:3]), 400)

        engine = str(request.data.get('engine') or 'agent_browser')
        if engine not in ('agent_browser', 'midscene'):
            return _err('engine 必须是 agent_browser 或 midscene', 400)

        suite = QaSuite.objects.create(
            project=project,
            name=base_name[:200],
            group=str(request.data.get('group') or ''),
            engine=engine,
            base_url=suite_info.base_url or str(request.data.get('base_url') or ''),
            description=str(request.data.get('description') or ''),
            yaml_content=content,
            source='manual',
            status='ready',
            created_by=request.user,
        )
        suite.test_count = count_tests(content)
        suite.save(update_fields=['test_count'])
        return Response(QaSuiteSerializer(suite).data, status=status.HTTP_201_CREATED)

    # ---------- 执行 ----------

    def run_suite(self, request, project_pk=None, pk=None):
        suite = self.get_object()
        if not suite.yaml_content.strip():
            return _err('套件 YAML 为空，无法执行', 400)
        run = QaRun.objects.create(
            suite=suite,
            status='pending',
            created_by=request.user,
        )
        run_web_qa_suite.delay(run.id)
        return Response({'run_id': run.id, 'status': 'pending'}, status=status.HTTP_202_ACCEPTED)

    def batch_run(self, request, project_pk=None):
        """POST {suite_ids?:[...] | group?:str} → {batch_id, runs:[{suite_id, run_id, status}]}"""
        project = self.get_project()
        suite_ids = request.data.get('suite_ids')
        group = str(request.data.get('group') or '').strip()

        if isinstance(suite_ids, str):
            try:
                suite_ids = [int(x) for x in suite_ids.split(',') if x.strip()]
            except ValueError:
                return _err('suite_ids 必须是整数列表', 400)
        if not suite_ids and group:
            suite_ids = list(
                QaSuite.objects.filter(project=project, group=group).values_list('id', flat=True)
            )
        if not suite_ids:
            return _err('请提供 suite_ids 列表或 group', 400)

        suites = list(QaSuite.objects.filter(id__in=suite_ids, project=project))
        if not suites:
            return _err('未找到可执行的套件', 400)

        batch = QaBatchRun.objects.create(
            project=project,
            name=str(request.data.get('name') or f'批量执行-{time_str()}'),
            group=group,
            suite_ids=[s.id for s in suites],
            status='pending',
            created_by=request.user,
        )

        runs = []
        for s in suites:
            run = QaRun.objects.create(suite=s, batch=batch, status='pending', created_by=request.user)
            runs.append({'suite_id': s.id, 'run_id': run.id, 'status': 'pending'})

        run_web_qa_batch.delay(batch.id)
        return Response({'batch_id': batch.id, 'runs': runs}, status=status.HTTP_202_ACCEPTED)

    # ---------- PRD 生成 ----------

    def prd_generate(self, request, project_pk=None):
        """POST {requirement_document_id?|text?} → {suite_id, status}"""
        from .prd_generator import extract_prd_text

        project = self.get_project()
        text = str(request.data.get('text') or '').strip()
        requirement_document_id = request.data.get('requirement_document_id')

        try:
            prd_text = extract_prd_text(
                requirement_document_id=requirement_document_id,
                text=text,
                project=project,
            )
        except ValueError as e:
            return _err(str(e), 400)

        if not prd_text.strip():
            return _err('PRD 文本为空', 400)

        name = str(request.data.get('name') or '').strip() or 'PRD 生成套件'
        llm_config_id = request.data.get('llm_config')
        if llm_config_id in ('', 'null', 'None'):
            llm_config_id = None

        suite = QaSuite.objects.create(
            project=project,
            name=name[:200],
            group=str(request.data.get('group') or ''),
            engine='midscene',
            base_url=str(request.data.get('base_url') or ''),
            description=prd_text[:20000],
            source='prd_generated',
            status='generating',
            llm_config_id=llm_config_id,
            created_by=request.user,
        )
        generate_web_qa_suite_from_prd.delay(suite.id)
        return Response({'suite_id': suite.id, 'status': 'generating'}, status=status.HTTP_202_ACCEPTED)

    # ---------- 定位缓存 ----------

    def locator_cache(self, request, project_pk=None):
        project = self.get_project()
        qs = AgentLocatorCache.objects.filter(project=project).order_by('-updated_at')
        strategy = request.query_params.get('strategy')
        if strategy:
            qs = qs.filter(strategy=strategy)
        return Response(AgentLocatorCacheSerializer(qs, many=True).data)

    def locator_cache_delete(self, request, project_pk=None, pk=None):
        project = self.get_project()
        entry = get_object_or_404(AgentLocatorCache, id=pk, project=project)
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class QaRunViewSet(viewsets.ReadOnlyModelViewSet):
    """执行记录查询 + 报告 + 取消。"""

    permission_classes = [IsAuthenticated, IsWebQaProjectMember]
    pagination_class = None

    def get_queryset(self):
        qs = QaRun.objects.filter(suite__project_id=self.kwargs.get('project_pk'))
        suite_id = self.request.query_params.get('suite_id')
        batch_id = self.request.query_params.get('batch_id')
        if suite_id:
            qs = qs.filter(suite_id=suite_id)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        return qs.select_related('suite', 'batch')

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset().order_by('-created_at')
        return Response(QaRunListSerializer(qs, many=True).data)

    def retrieve(self, request, *args, **kwargs):
        run = self.get_object()
        steps = QaStepResult.objects.filter(run=run).order_by('test_index', 'step_index')
        return Response({
            'run': QaRunSerializer(run).data,
            'steps': QaStepResultSerializer(steps, many=True).data,
        })

    def report_md(self, request, *args, **kwargs):
        run = self.get_object()
        return Response({'report': run.report_md or ''})

    def cancel(self, request, *args, **kwargs):
        run = self.get_object()
        if run.status in ('pending', 'running'):
            run.status = 'cancelled'
            run.error = '已取消'
            run.save(update_fields=['status', 'error'])
        return Response(QaRunSerializer(run).data)


def time_str():
    from django.utils import timezone
    return timezone.now().strftime('%Y%m%d%H%M%S')
