"""code_analysis REST API 视图。"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from projects.models import Project

from .ingest import ingest_zip
from .models import (
    ChangeImpactRecord,
    CodeFile,
    CodeProject,
    CodeProjectSnapshot,
    ComponentAnalysisTask,
    ElementSuggestion,
    SpecAnalysisSuggestion,
    SpecAnalysisTask,
    TestCodeLink,
)
from .permissions import IsCodeProjectMember
from .serializers import (
    ChangeImpactRecordSerializer,
    CodeFileListSerializer,
    CodeProjectSerializer,
    ComponentAnalysisTaskSerializer,
    ElementSuggestionSerializer,
    SpecAnalysisSuggestionSerializer,
    SpecAnalysisTaskSerializer,
    TestCodeLinkSerializer,
)
from .tasks import (
    auto_detect_changes,
    run_component_analysis,
    run_git_import,
    run_spec_analysis,
)

logger = logging.getLogger('code_analysis')

DEFAULT_GROUP_NAME = 'AI源码分析'

SPEC_EXTENSIONS = ('.json', '.yaml', '.yml')

# OpenAPI 建议 priority -> api_testcases priority
PRIORITY_MAP = {'high': 'P1', 'medium': 'P2', 'low': 'P3'}


def _err(message, code=400):
    return Response({'detail': message}, status=code)


def _unique_name(model, base_name, **extra_filters):
    """在 project 作用域下生成唯一名称（追加 2/3/4... 后缀）。"""
    candidate = base_name
    suffix = 2
    while model.objects.filter(name=candidate, **extra_filters).exists():
        candidate = f'{base_name} {suffix}'
        suffix += 1
    return candidate


def _import_spec_suggestion(suggestion, code_project, user):
    """将一条 Spec 建议导入为 ApiInterface + ApiTestCase + ApiTestCaseStep。"""
    from api_interfaces.models import ApiInterface
    from api_testcases.models import ApiTestCase, ApiTestCaseGroup, ApiTestCaseStep

    payload = suggestion.payload or {}
    method = payload.get('method') or 'GET'
    path = payload.get('path') or ''
    project = code_project.project
    interface_name = f'{method} {path}'

    interface, created = ApiInterface.objects.get_or_create(
        name=interface_name,
        project=project,
        defaults={
            'type': ApiInterface.TYPE_HTTP,
            'method': method,
            'url': path,
            'headers': {},
            'params': {},
            'body': {},
            'created_by': user,
        },
    )

    group_name = payload.get('target_module') or DEFAULT_GROUP_NAME
    group, _ = ApiTestCaseGroup.objects.get_or_create(
        name=group_name, parent=None, project=project,
        defaults={'created_by': user},
    )

    base_name = payload.get('name') or f'{interface_name} 测试'
    tc_name = _unique_name(ApiTestCase, base_name, project=project)
    testcase = ApiTestCase.objects.create(
        name=tc_name,
        description=payload.get('description') or '',
        priority=PRIORITY_MAP.get(payload.get('priority'), 'P2'),
        config={},
        file_ids=[],
        project=project,
        group=group,
        created_by=user,
    )
    ApiTestCaseStep.objects.create(
        name=payload.get('name') or interface_name,
        order=1,
        interface_data=interface.get_interface_data(),
        config={},
        file_ids=[],
        testcase=testcase,
        origin_interface=interface,
        sync_fields=[],
    )

    suggestion.status = 'imported'
    suggestion.imported_interface_id = interface.id
    suggestion.imported_testcase_id = testcase.id
    suggestion.save(update_fields=['status', 'imported_interface_id', 'imported_testcase_id'])

    # 自动建立 测试用例 <-> Spec 文件 关联
    try:
        from .models import TestCodeLink
        TestCodeLink.objects.get_or_create(
            project=project,
            testcase_type='api',
            testcase_id=testcase.id,
            path=suggestion.task.spec_name or '/',
            defaults={
                'symbol': payload.get('name'),
                'status': 'linked',
                'created_by': user,
            },
        )
    except Exception as e:
        logger.warning('[code_analysis] auto-link spec suggestion %s failed: %s', suggestion.id, e)

    return {
        'status': 'created',
        'interface_id': interface.id,
        'testcase_id': testcase.id,
        'interface_created': created,
        'message': '',
    }


def _import_element_suggestion(suggestion, code_project, user):
    """将一条元素建议导入为 UiPage + UiElement。"""
    from ui_automation.models import UiElement, UiModule, UiPage

    project = code_project.project
    payload = suggestion.payload or {}
    slots = payload.get('locator_slots') or {}
    primary = slots.get('primary') or {}
    backups = slots.get('backups') or []
    iframe = slots.get('iframe')

    module, _ = UiModule.objects.get_or_create(
        name=DEFAULT_GROUP_NAME, parent=None, project=project,
        defaults={'creator': user},
    )
    page, page_created = UiPage.objects.get_or_create(
        name=payload.get('page_name') or '未命名页面',
        project=project,
        defaults={
            'module': module,
            'description': payload.get('file_path') or '',
            'creator': user,
        },
    )

    element = UiElement.objects.create(
        page=page,
        name=(payload.get('element_name') or 'element')[:64],
        locator_type=primary.get('type') or 'xpath',
        locator_value=primary.get('value') or '',
        locator_index=primary.get('index'),
        locator_type_2=backups[0].get('type') if len(backups) > 0 else None,
        locator_value_2=backups[0].get('value') if len(backups) > 0 else None,
        locator_index_2=backups[0].get('index') if len(backups) > 0 else None,
        locator_type_3=backups[1].get('type') if len(backups) > 1 else None,
        locator_value_3=backups[1].get('value') if len(backups) > 1 else None,
        locator_index_3=backups[1].get('index') if len(backups) > 1 else None,
        wait_time=0,
        is_iframe=bool(iframe),
        iframe_locator=(iframe or {}).get('value') if iframe else None,
        description=payload.get('file_path') or '',
        creator=user,
    )

    suggestion.status = 'imported'
    suggestion.imported_page_id = page.id
    suggestion.imported_element_id = element.id
    suggestion.save(update_fields=['status', 'imported_page_id', 'imported_element_id'])

    # 自动建立 测试用例(UiElement) <-> 组件源码文件 关联
    try:
        from .models import TestCodeLink
        code_file = None
        file_path = payload.get('file_path') or ''
        snapshot = getattr(suggestion.task, 'snapshot', None)
        if snapshot is not None and file_path:
            code_file = snapshot.files.filter(path=file_path, is_deleted=False).first()
        TestCodeLink.objects.get_or_create(
            project=project,
            testcase_type='ui',
            testcase_id=element.id,
            path=code_file.path if code_file else file_path,
            defaults={
                'code_file': code_file,
                'symbol': payload.get('element_name'),
                'locator_ref': (slots.get('primary') or {}).get('value'),
                'status': 'linked',
                'created_by': user,
            },
        )
    except Exception as e:
        logger.warning('[code_analysis] auto-link element suggestion %s failed: %s', suggestion.id, e)

    return {
        'status': 'created',
        'page_id': page.id,
        'element_id': element.id,
        'page_created': page_created,
        'message': '',
    }


class CodeProjectViewSet(viewsets.ModelViewSet):
    """代码项目 CRUD + zip 上传 + 文件列表/内容。"""

    serializer_class = CodeProjectSerializer
    permission_classes = [IsAuthenticated, IsCodeProjectMember]
    pagination_class = None

    def get_queryset(self):
        return CodeProject.objects.filter(project_id=self.kwargs.get('project_pk'))

    def get_project(self):
        return get_object_or_404(Project, pk=self.kwargs.get('project_pk'))

    def perform_create(self, serializer):
        serializer.save(project=self.get_project(), created_by=self.request.user)

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        return Response(CodeProjectSerializer(qs, many=True).data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return Response(CodeProjectSerializer(instance).data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(CodeProjectSerializer(serializer.instance).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='upload')
    def upload(self, request, project_pk=None, pk=None):
        code_project = self.get_object()
        zip_file = request.FILES.get('file')
        if not zip_file:
            return _err('缺少 file 字段（multipart zip）', 400)
        name = (zip_file.name or '').lower()
        try:
            zip_file.seek(0)
            magic = zip_file.read(4)
            zip_file.seek(0)
        except Exception:
            magic = b''
        if not name.endswith('.zip') and magic != b'PK\x03\x04':
            return _err('仅支持 .zip 格式的代码包', 400)
        try:
            snapshot, file_count, skipped = ingest_zip(zip_file, code_project, request.user)
            # 自动检测变更影响（≥2 快照时，异步不阻塞上传响应）
            if snapshot.version_no >= 2:
                auto_detect_changes.delay(code_project.id, snapshot.id)
            return Response({
                'snapshot_id': snapshot.id,
                'version_no': snapshot.version_no,
                'file_count': file_count,
                'skipped_count': skipped,
            }, status=status.HTTP_201_CREATED)
        except DjangoValidationError as e:
            return _err(e.messages[0] if e.messages else str(e), 400)
        except Exception as e:
            logger.exception('[code_analysis] zip upload failed: %s', e)
            return _err('上传失败', 500)

    @action(detail=True, methods=['get'], url_path='files')
    def files(self, request, project_pk=None, pk=None):
        code_project = self.get_object()
        snapshot_id = request.query_params.get('snapshot_id')
        snapshots = code_project.snapshots.all()
        if snapshot_id:
            snapshots = snapshots.filter(id=snapshot_id)
        snapshot = snapshots.order_by('-version_no').first()
        if snapshot is None:
            return Response({'snapshot_id': None, 'version_no': None, 'files': []})

        qs = CodeFile.objects.filter(snapshot=snapshot, is_deleted=False)
        path_prefix = request.query_params.get('path_prefix')
        if path_prefix:
            qs = qs.filter(path__startswith=path_prefix)
        q = request.query_params.get('q')
        if q:
            qs = qs.filter(path__icontains=q)
        qs = qs.order_by('path')
        return Response({
            'snapshot_id': snapshot.id,
            'version_no': snapshot.version_no,
            'files': CodeFileListSerializer(qs, many=True).data,
        })

    @action(detail=True, methods=['get'], url_path=r'files/(?P<file_id>[0-9]+)/content')
    def file_content(self, request, project_pk=None, pk=None, file_id=None):
        code_project = self.get_object()
        cf = get_object_or_404(CodeFile, id=file_id, snapshot__code_project=code_project)
        if not cf.content_stored or cf.content is None:
            return _err('该文件内容未存储（二进制文件或超过 200KB）', 404)
        return Response({
            'path': cf.path,
            'language': cf.language,
            'size': cf.size,
            'content': cf.content,
        })

    @action(detail=True, methods=['post'], url_path='analyze-changes')
    def analyze_changes(self, request, project_pk=None, pk=None):
        """对比当前快照与上一快照，检测变更影响。"""
        code_project = self.get_object()
        if code_project.snapshots.count() < 2:
            return _err('至少需要两个快照才能进行变更分析', 400)
        snapshot = code_project.current_snapshot or code_project.snapshots.order_by('-version_no').first()
        from .linkage import detect_changes
        summary = detect_changes(code_project, snapshot)
        return Response(summary)

    @action(detail=True, methods=['post'], url_path='git-import')
    def git_import(self, request, project_pk=None, pk=None):
        """通过 git URL 导入代码（https），异步 clone。"""
        from urllib.parse import urlparse

        code_project = self.get_object()
        git_url = str(request.data.get('git_url') or '').strip()
        branch = str(request.data.get('branch') or '').strip() or None

        parsed = urlparse(git_url)
        if parsed.scheme != 'https' or not parsed.netloc:
            return _err('仅支持 https 协议的 Git 地址', 400)

        code_project.git_url = git_url
        code_project.source_type = 'git_url'
        if branch:
            code_project.repo_branch = branch
        code_project.save(update_fields=['git_url', 'repo_branch', 'source_type', 'updated_at'])

        version_no = code_project.snapshots.count() + 1
        snapshot = CodeProjectSnapshot.objects.create(
            code_project=code_project,
            version_no=version_no,
            commit_ref='pending',
            created_by=request.user,
        )
        run_git_import.delay(snapshot.id)
        return Response({
            'snapshot_id': snapshot.id,
            'version_no': snapshot.version_no,
            'status': 'pending',
        }, status=status.HTTP_202_ACCEPTED)

    # ---------- 测试用例 <-> 代码 关联 ----------

    @action(detail=True, methods=['get'], url_path='links')
    def list_links(self, request, project_pk=None, pk=None):
        code_project = self.get_object()
        qs = TestCodeLink.objects.filter(project=code_project.project).select_related('code_file')
        status_f = request.query_params.get('status')
        if status_f:
            qs = qs.filter(status=status_f)
        qs = qs.order_by('-updated_at')
        return Response(TestCodeLinkSerializer(qs, many=True).data)

    @action(detail=True, methods=['post'], url_path='links')
    def create_link(self, request, project_pk=None, pk=None):
        code_project = self.get_object()
        testcase_type = str(request.data.get('testcase_type') or '').strip()
        if testcase_type not in ('functional', 'api', 'ui'):
            return _err('testcase_type 必须是 functional/api/ui', 400)
        try:
            testcase_id = int(request.data.get('testcase_id'))
        except (TypeError, ValueError):
            return _err('testcase_id 必须是整数', 400)

        code_file_id = request.data.get('code_file_id')
        path = str(request.data.get('path') or '').strip() or None
        code_file = None
        if code_file_id:
            code_file = get_object_or_404(
                CodeFile, id=code_file_id, snapshot__code_project__project=code_project.project
            )
            path = code_file.path
        if not path:
            return _err('必须提供 code_file_id 或 path', 400)

        symbol = str(request.data.get('symbol') or '').strip() or None
        locator_ref = str(request.data.get('locator_ref') or '').strip() or None

        existing = TestCodeLink.objects.filter(
            project=code_project.project,
            testcase_type=testcase_type,
            testcase_id=testcase_id,
            path=path,
        ).first()
        if existing:
            return Response({'link': TestCodeLinkSerializer(existing).data, 'created': False})

        link = TestCodeLink.objects.create(
            project=code_project.project,
            testcase_type=testcase_type,
            testcase_id=testcase_id,
            code_file=code_file,
            path=path,
            symbol=symbol,
            locator_ref=locator_ref,
            status='linked',
            created_by=request.user,
        )
        return Response(TestCodeLinkSerializer(link).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path=r'links/(?P<link_id>[0-9]+)')
    def delete_link(self, request, project_pk=None, pk=None, link_id=None):
        code_project = self.get_object()
        link = get_object_or_404(TestCodeLink, id=link_id, project=code_project.project)
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ---------- 变更影响记录 ----------

    @action(detail=True, methods=['get'], url_path='impacts')
    def list_impacts(self, request, project_pk=None, pk=None):
        code_project = self.get_object()
        qs = ChangeImpactRecord.objects.filter(
            snapshot__code_project=code_project
        ).select_related('snapshot', 'code_file')
        resolved_f = request.query_params.get('resolved')
        if resolved_f in ('true', '1', 'yes'):
            qs = qs.filter(resolved=True)
        elif resolved_f in ('false', '0', 'no'):
            qs = qs.filter(resolved=False)
        qs = qs.order_by('-created_at')
        return Response(ChangeImpactRecordSerializer(qs, many=True).data)

    @action(detail=True, methods=['post'], url_path=r'impacts/(?P<impact_id>[0-9]+)/resolve')
    def resolve_impact(self, request, project_pk=None, pk=None, impact_id=None):
        from django.utils import timezone

        code_project = self.get_object()
        impact = get_object_or_404(ChangeImpactRecord, id=impact_id, snapshot__code_project=code_project)
        if not impact.resolved:
            impact.resolved = True
            impact.save(update_fields=['resolved'])
            link = TestCodeLink.objects.filter(
                project=code_project.project,
                testcase_type=impact.testcase_type,
                testcase_id=impact.testcase_id,
                path=impact.path,
            ).first()
            if link:
                link.status = 'linked'
                link.last_verified_at = timezone.now()
                link.save(update_fields=['status', 'last_verified_at', 'updated_at'])
        return Response(ChangeImpactRecordSerializer(impact).data)


class SpecAnalysisViewSet(viewsets.ModelViewSet):
    """OpenAPI 规范分析任务。"""

    serializer_class = SpecAnalysisTaskSerializer
    permission_classes = [IsAuthenticated, IsCodeProjectMember]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None

    def get_queryset(self):
        return SpecAnalysisTask.objects.filter(
            code_project__project_id=self.kwargs.get('project_pk')
        ).select_related('code_project')

    def get_project(self):
        return get_object_or_404(Project, pk=self.kwargs.get('project_pk'))

    def list(self, request, *args, **kwargs):
        return Response(SpecAnalysisTaskSerializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, *args, **kwargs):
        return Response(SpecAnalysisTaskSerializer(self.get_object()).data)

    def create(self, request, *args, **kwargs):
        project = self.get_project()
        code_project_id = request.data.get('code_project')
        if not code_project_id:
            return _err('缺少 code_project（代码项目 ID）', 400)
        code_project = get_object_or_404(CodeProject, id=code_project_id, project=project)

        use_llm = str(request.data.get('use_llm', '')).lower() in ('true', '1', 'yes')
        spec_file = request.FILES.get('file')
        spec_url = str(request.data.get('spec_url') or '').strip()

        if spec_file and spec_url:
            return _err('file 与 spec_url 只能二选一', 400)
        if not spec_file and not spec_url:
            return _err('请上传 spec 文件或提供 spec_url', 400)

        if spec_file:
            name = spec_file.name or 'spec.yaml'
            ext = Path(name).suffix.lower()
            if ext not in SPEC_EXTENSIONS:
                # 根据内容嗅探格式，兼容未携带扩展名的上传
                head = spec_file.read(512).lstrip()
                spec_file.seek(0)
                if head.startswith(b'{') or head.startswith(b'['):
                    ext = '.json'
                elif head[:1] in (b'-', b'{', b'o') and (b'openapi' in head.lower() or b'swagger' in head.lower()):
                    ext = '.yaml'
                else:
                    ext = ''
            if ext not in SPEC_EXTENSIONS:
                return _err('仅支持 .json / .yaml 格式的 OpenAPI 文档', 400)
            task = SpecAnalysisTask.objects.create(
                code_project=code_project, source='upload',
                spec_name=name, use_llm=use_llm, created_by=request.user,
            )
            spec_dir = Path(settings.MEDIA_ROOT) / 'code_projects' / 'specs'
            spec_dir.mkdir(parents=True, exist_ok=True)
            with open(spec_dir / f'spec_{task.id}{ext}', 'wb+') as fh:
                for chunk in spec_file.chunks():
                    fh.write(chunk)
        else:
            task = SpecAnalysisTask.objects.create(
                code_project=code_project, source='spec_url',
                spec_name=spec_url, use_llm=use_llm, created_by=request.user,
            )

        run_spec_analysis.delay(task.id)
        task.refresh_from_db()
        return Response(SpecAnalysisTaskSerializer(task).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='suggestions')
    def suggestions(self, request, project_pk=None, pk=None):
        task = self.get_object()
        qs = task.suggestions.all()
        status_f = request.query_params.get('status')
        if status_f:
            qs = qs.filter(status=status_f)
        qs = qs.order_by('id')
        return Response(SpecAnalysisSuggestionSerializer(qs, many=True).data)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, project_pk=None, pk=None):
        task = self.get_object()
        suggestion_ids = request.data.get('suggestion_ids') or []
        if not isinstance(suggestion_ids, list) or not suggestion_ids:
            return _err('缺少 suggestion_ids 列表', 400)

        suggestions = list(task.suggestions.filter(id__in=suggestion_ids))
        results = []
        for s in suggestions:
            if s.status == 'imported':
                results.append({
                    'suggestion_id': s.id,
                    'status': 'skipped',
                    'message': '已导入，跳过',
                })
                continue
            try:
                result = _import_spec_suggestion(s, task.code_project, request.user)
                results.append({'suggestion_id': s.id, **result})
            except Exception as e:
                logger.exception('[code_analysis] import spec suggestion %s failed: %s', s.id, e)
                results.append({
                    'suggestion_id': s.id,
                    'status': 'error',
                    'message': str(e),
                })
        return Response({'results': results})

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, project_pk=None, pk=None):
        task = self.get_object()
        suggestion_ids = request.data.get('suggestion_ids') or []
        if not isinstance(suggestion_ids, list) or not suggestion_ids:
            return _err('缺少 suggestion_ids 列表', 400)
        updated = task.suggestions.filter(id__in=suggestion_ids).exclude(status='imported').update(status='rejected')
        return Response({'updated': updated})


class ComponentAnalysisViewSet(viewsets.ModelViewSet):
    """前端组件源码分析任务。"""

    serializer_class = ComponentAnalysisTaskSerializer
    permission_classes = [IsAuthenticated, IsCodeProjectMember]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None

    def get_queryset(self):
        return ComponentAnalysisTask.objects.filter(
            code_project__project_id=self.kwargs.get('project_pk')
        ).select_related('code_project', 'snapshot')

    def get_project(self):
        return get_object_or_404(Project, pk=self.kwargs.get('project_pk'))

    def list(self, request, *args, **kwargs):
        return Response(ComponentAnalysisTaskSerializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, *args, **kwargs):
        return Response(ComponentAnalysisTaskSerializer(self.get_object()).data)

    def create(self, request, *args, **kwargs):
        project = self.get_project()
        code_project_id = request.data.get('code_project')
        if not code_project_id:
            return _err('缺少 code_project（代码项目 ID）', 400)
        code_project = get_object_or_404(CodeProject, id=code_project_id, project=project)

        snapshot = None
        snapshot_id = request.data.get('snapshot_id')
        if snapshot_id:
            snapshot = get_object_or_404(code_project.snapshots, id=snapshot_id)

        file_filter = request.data.get('file_filter')
        if isinstance(file_filter, str) and file_filter.strip():
            file_filter = [p.strip() for p in file_filter.split(',') if p.strip()]
        if not isinstance(file_filter, (list, type(None))):
            file_filter = None

        task = ComponentAnalysisTask.objects.create(
            code_project=code_project,
            snapshot=snapshot,
            file_filter=file_filter,
            created_by=request.user,
        )
        run_component_analysis.delay(task.id)
        task.refresh_from_db()
        return Response(ComponentAnalysisTaskSerializer(task).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='element-suggestions')
    def element_suggestions(self, request, project_pk=None, pk=None):
        task = self.get_object()
        qs = task.element_suggestions.all()
        status_f = request.query_params.get('status')
        if status_f:
            qs = qs.filter(status=status_f)
        qs = qs.order_by('id')
        return Response(ElementSuggestionSerializer(qs, many=True).data)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, project_pk=None, pk=None):
        task = self.get_object()
        suggestion_ids = request.data.get('suggestion_ids') or []
        if not isinstance(suggestion_ids, list) or not suggestion_ids:
            return _err('缺少 suggestion_ids 列表', 400)

        suggestions = list(task.element_suggestions.filter(id__in=suggestion_ids))
        results = []
        for s in suggestions:
            if s.status == 'imported':
                results.append({
                    'suggestion_id': s.id,
                    'status': 'skipped',
                    'message': '已导入，跳过',
                })
                continue
            try:
                result = _import_element_suggestion(s, task.code_project, request.user)
                results.append({'suggestion_id': s.id, **result})
            except Exception as e:
                logger.exception('[code_analysis] import element suggestion %s failed: %s', s.id, e)
                results.append({
                    'suggestion_id': s.id,
                    'status': 'error',
                    'message': str(e),
                })
        return Response({'results': results})

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, project_pk=None, pk=None):
        task = self.get_object()
        suggestion_ids = request.data.get('suggestion_ids') or []
        if not isinstance(suggestion_ids, list) or not suggestion_ids:
            return _err('缺少 suggestion_ids 列表', 400)
        updated = task.element_suggestions.filter(id__in=suggestion_ids).exclude(status='imported').update(status='rejected')
        return Response({'updated': updated})
