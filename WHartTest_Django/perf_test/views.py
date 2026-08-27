import logging

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.response import Response

from wharttest_django.pagination import StandardPagination
from wharttest_django.viewsets import BaseModelViewSet

from projects.models import Project

from .models import (
    PerfTestScenario,
    PerfTestRequest,
    PerfTestPlan,
    PerfTestExecution,
    PerfTestReport,
    PerfTestNode,
)
from .serializers import (
    PerfTestScenarioSerializer,
    PerfTestRequestSerializer,
    PerfTestPlanSerializer,
    PerfTestExecutionSerializer,
    PerfTestReportSerializer,
    PerfTestNodeSerializer,
)
from .services import (
    build_requests_from_interfaces,
    import_har,
    import_swagger,
    render_locustfile,
)
from .templates import get_template, list_templates
from .distributed import (
    distributed_enabled,
    claim_task,
    apply_progress,
    apply_report,
)

logger = logging.getLogger(__name__)

_REQUEST_FIELDS = (
    'name', 'method', 'url', 'headers', 'params', 'body',
    'variables', 'validators', 'weight', 'order',
)


def _requests_to_dicts(scenario):
    return list(
        scenario.requests.values(*_REQUEST_FIELDS).order_by('order', 'id')
    )


def _bulk_create_requests(scenario, requests):
    objs = [
        PerfTestRequest(scenario=scenario, **request) for request in requests
    ]
    return PerfTestRequest.objects.bulk_create(objs)


def _dispatch_execution(execution):
    """将执行记录置为待执行并投递 Celery 任务。"""
    plan = PerfTestPlan.objects.filter(scenario=execution.scenario).first()
    execution.plan_snapshot = (
        {
            'users': plan.users,
            'spawn_rate': plan.spawn_rate,
            'duration': plan.duration,
            'think_time': plan.think_time,
            'target_qps': plan.target_qps,
        }
        if plan
        else {}
    )
    execution.status = 'pending'
    execution.progress = 0
    execution.error_message = ''
    execution.save()

    # 绑定在线节点且分布式启用时，走 worker 拉取路径（不再本地投递 Celery）
    if plan and distributed_enabled() and plan.node and plan.node.status == 'online':
        logger.info(f"执行将分发到节点执行 execution={execution.id} node={plan.node_id}")
        return execution

    from .tasks import run_perf_test

    result = run_perf_test.delay(execution.id)
    execution.celery_task_id = result.id
    execution.save(update_fields=['celery_task_id'])
    return execution


class PerfTestScenarioViewSet(BaseModelViewSet):
    queryset = PerfTestScenario.objects.all()
    serializer_class = PerfTestScenarioSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['project', 'source']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return PerfTestScenario.objects.prefetch_related('requests', 'plan').all()
        return PerfTestScenario.objects.prefetch_related(
            'requests', 'plan'
        ).filter(project__members__user=user).distinct()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def render(self, request, pk=None):
        scenario = self.get_object()
        plan = PerfTestPlan.objects.filter(scenario=scenario).first()
        think_time = plan.think_time if plan else 0
        locustfile = render_locustfile(_requests_to_dicts(scenario), think_time)
        scenario.locustfile = locustfile
        scenario.save(update_fields=['locustfile'])
        return Response({'locustfile': locustfile})

    @action(detail=True, methods=['post'])
    def import_interfaces(self, request, pk=None):
        scenario = self.get_object()
        interface_ids = request.data.get('interface_ids') or []
        if not isinstance(interface_ids, list) or not interface_ids:
            return Response(
                {'error': 'interface_ids 必须是非空列表'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        requests = build_requests_from_interfaces(interface_ids)
        created = _bulk_create_requests(scenario, requests)
        return Response(
            {'created': len(created)},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def import_swagger(self, request, pk=None):
        scenario = self.get_object()
        spec = request.data.get('spec')
        if not isinstance(spec, dict):
            return Response(
                {'error': 'spec 必须是 JSON 对象'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        created = _bulk_create_requests(scenario, import_swagger(spec))
        return Response(
            {'created': len(created)},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def import_har(self, request, pk=None):
        scenario = self.get_object()
        har = request.data.get('har')
        if isinstance(har, str) or isinstance(har, dict):
            created = _bulk_create_requests(scenario, import_har(har))
        else:
            return Response(
                {'error': 'har 必须是 JSON 字符串或对象'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {'created': len(created)},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        scenario = self.get_object()
        execution = PerfTestExecution.objects.create(
            scenario=scenario,
            executed_by=request.user,
            status='pending',
        )
        _dispatch_execution(execution)
        return Response(
            PerfTestExecutionSerializer(execution).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['get'])
    def templates(self, request):
        return Response(list_templates())

    @action(detail=False, methods=['post'])
    def create_from_template(self, request):
        template = get_template(request.data.get('template'))
        if not template:
            return Response(
                {'error': '无效的模板标识'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        project = self._resolve_project(request.data.get('project_id'), request)
        if project is None:
            return Response(
                {'error': '项目不存在或无权访问'},
                status=status.HTTP_403_FORBIDDEN,
            )
        scenario = PerfTestScenario.objects.create(
            name=request.data.get('name') or template['name'],
            description=template['description'],
            source='ai',
            project=project,
            created_by=request.user,
        )
        _bulk_create_requests(scenario, template['requests'])
        PerfTestPlan.objects.create(scenario=scenario, **template['plan'])
        return Response(
            PerfTestScenarioSerializer(scenario).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['post'])
    def ai_orchestrate(self, request):
        requirement = (request.data.get('requirement') or '').strip()
        if not requirement:
            return Response(
                {'error': 'requirement 不能为空'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        project = self._resolve_project(request.data.get('project_id'), request)
        if project is None:
            return Response(
                {'error': '项目不存在或无权访问'},
                status=status.HTTP_403_FORBIDDEN,
            )
        interface_ids = request.data.get('interface_ids') or []
        from .orchestrate import orchestrate_scenario

        scenario, _ = orchestrate_scenario(
            project, request.user, requirement, interface_ids
        )
        return Response(
            PerfTestScenarioSerializer(scenario).data,
            status=status.HTTP_201_CREATED,
        )

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


class PerfTestRequestViewSet(BaseModelViewSet):
    queryset = PerfTestRequest.objects.all()
    serializer_class = PerfTestRequestSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['scenario', 'method']
    ordering_fields = ['order', 'created_at']
    ordering = ['order', 'id']

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return PerfTestRequest.objects.all()
        return PerfTestRequest.objects.filter(
            scenario__project__members__user=user
        ).distinct()


class PerfTestPlanViewSet(BaseModelViewSet):
    queryset = PerfTestPlan.objects.all()
    serializer_class = PerfTestPlanSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['scenario']
    ordering_fields = ['created_at', 'updated_at']

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return PerfTestPlan.objects.all()
        return PerfTestPlan.objects.filter(
            scenario__project__members__user=user
        ).distinct()


class PerfTestExecutionViewSet(BaseModelViewSet):
    queryset = PerfTestExecution.objects.all()
    serializer_class = PerfTestExecutionSerializer
    pagination_class = StandardPagination
    http_method_names = ['get', 'post', 'head', 'options']
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['scenario', 'status']
    ordering_fields = ['created_at']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        base = PerfTestExecution.objects.select_related('scenario', 'executed_by')
        if user.is_superuser:
            return base.all()
        return base.filter(scenario__project__members__user=user).distinct()

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        execution = self.get_object()
        if execution.status == 'running':
            return Response(
                {'error': '执行已在进行中'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _dispatch_execution(execution)
        return Response(PerfTestExecutionSerializer(execution).data)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        execution = self.get_object()
        if execution.status != 'running':
            return Response(
                {'error': '执行未在运行中'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if execution.celery_task_id:
            from celery import current_app

            current_app.control.revoke(execution.celery_task_id, terminate=True)
        execution.cancel()
        return Response(PerfTestExecutionSerializer(execution).data)


class PerfTestReportViewSet(BaseModelViewSet):
    queryset = PerfTestReport.objects.all()
    serializer_class = PerfTestReportSerializer
    pagination_class = StandardPagination
    http_method_names = ['get', 'head', 'options']
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['execution']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        base = PerfTestReport.objects.select_related('execution')
        if user.is_superuser:
            return base.all()
        return base.filter(
            execution__scenario__project__members__user=user
        ).distinct()

    @action(detail=True, methods=['post'])
    def diagnose(self, request, pk=None):
        report = self.get_object()
        from .tasks import diagnose_perf_report

        result = diagnose_perf_report.delay(report.id)
        return Response({'task_id': result.id, 'report_id': report.id})


class PerfTestNodeViewSet(BaseModelViewSet):
    queryset = PerfTestNode.objects.all()
    serializer_class = PerfTestNodeSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status']
    search_fields = ['name', 'host']
    ordering = ['-created_at']

    @action(detail=False, methods=['post'])
    def heartbeat(self, request):
        name = request.data.get('name')
        host = request.data.get('host')
        if not name:
            return Response(
                {'error': 'name 不能为空'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        node, _ = PerfTestNode.objects.update_or_create(
            name=name,
            defaults={
                'host': host or '',
                'status': 'online',
                'cpu_usage': float(request.data.get('cpu_usage') or 0),
                'memory_usage': float(request.data.get('memory_usage') or 0),
                'last_heartbeat': timezone.now(),
            },
        )
        return Response(PerfTestNodeSerializer(node).data)

    @action(detail=True, methods=['post'])
    def claim(self, request, pk=None):
        """worker 拉取任务：认领绑定到该节点的一个待执行压测。"""
        execution, payload = claim_task(pk)
        if payload is None:
            return Response({'has_task': False})
        return Response({'has_task': True, 'task': payload})

    @action(detail=True, methods=['post'])
    def progress(self, request, pk=None):
        """worker 上报执行进度，刷新进度并推送实时面板。"""
        execution_id = request.data.get('execution_id')
        if not execution_id:
            return Response(
                {'error': 'execution_id 必填'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        apply_progress(
            execution_id,
            float(request.data.get('progress') or 0),
            float(request.data.get('rps') or 0),
            float(request.data.get('users') or 0),
        )
        return Response({'ok': True})

    @action(detail=True, methods=['post'])
    def report(self, request, pk=None):
        """worker 回传执行结果：成功落库报告，失败标记失败。"""
        execution_id = request.data.get('execution_id')
        if not execution_id:
            return Response(
                {'error': 'execution_id 必填'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        report_id = apply_report(
            execution_id,
            request.data.get('stats') or {},
            request.data.get('series') or [],
            request.data.get('error') or '',
        )
        return Response({'ok': True, 'report_id': report_id})
