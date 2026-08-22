from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from projects.models import Project


class PerfTestScenario(models.Model):
    """性能测试场景，聚合一组请求模板与负载模型"""

    SOURCE_CHOICES = [
        ('interface', '接口定义'),
        ('swagger', 'Swagger/OpenAPI'),
        ('har', 'HAR 文件'),
        ('ai', 'AI 编排'),
    ]

    name = models.CharField(_('场景名称'), max_length=200)
    description = models.TextField(_('场景描述'), blank=True)
    source = models.CharField(
        _('来源'), max_length=20, choices=SOURCE_CHOICES, default='interface'
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='perf_test_scenarios',
        verbose_name=_('所属项目'),
    )
    locustfile = models.TextField(
        _('Locust 脚本缓存'), blank=True,
        help_text='请求模板渲染出的 locustfile 字符串缓存',
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='perf_test_scenarios_created',
        verbose_name=_('创建人'),
    )
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        verbose_name = _('性能测试场景')
        verbose_name_plural = _('性能测试场景')
        ordering = ['-created_at']
        unique_together = ['name', 'project']
        indexes = [
            models.Index(fields=['project', 'created_at'], name='perf_scenario_proj_created_idx'),
        ]

    def __str__(self):
        return self.name


class PerfTestRequest(models.Model):
    """请求模板，对应场景中的一个 HTTP 请求"""

    METHOD_CHOICES = [
        ('GET', 'GET'),
        ('POST', 'POST'),
        ('PUT', 'PUT'),
        ('DELETE', 'DELETE'),
        ('PATCH', 'PATCH'),
        ('HEAD', 'HEAD'),
        ('OPTIONS', 'OPTIONS'),
    ]

    scenario = models.ForeignKey(
        PerfTestScenario,
        on_delete=models.CASCADE,
        related_name='requests',
        verbose_name=_('所属场景'),
    )
    name = models.CharField(_('请求名称'), max_length=200)
    method = models.CharField(
        _('HTTP 方法'), max_length=10, choices=METHOD_CHOICES, default='GET'
    )
    url = models.TextField(_('URL'), blank=True)
    headers = models.JSONField(_('请求头'), default=dict, blank=True)
    params = models.JSONField(_('查询参数'), default=dict, blank=True)
    body = models.JSONField(_('请求体'), default=dict, blank=True)
    variables = models.JSONField(_('动态参数'), default=dict, blank=True)
    validators = models.JSONField(_('断言规则'), default=list, blank=True)
    weight = models.IntegerField(_('权重'), default=1)
    order = models.IntegerField(_('顺序'), default=0)

    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)

    class Meta:
        verbose_name = _('压测请求模板')
        verbose_name_plural = _('压测请求模板')
        ordering = ['order', 'id']
        indexes = [
            models.Index(fields=['scenario', 'order'], name='perf_req_scenario_order_idx'),
        ]

    def __str__(self):
        return f"{self.scenario.name}-{self.name}"


class PerfTestPlan(models.Model):
    """负载模型，描述并发用户、爬坡与持续时间"""

    scenario = models.OneToOneField(
        PerfTestScenario,
        on_delete=models.CASCADE,
        related_name='plan',
        verbose_name=_('所属场景'),
    )
    users = models.IntegerField(_('并发用户数'), default=10)
    spawn_rate = models.IntegerField(_('每秒启动用户数'), default=1)
    duration = models.IntegerField(_('持续时间(秒)'), default=60)
    think_time = models.FloatField(_('思考时间(秒)'), default=0)
    target_qps = models.IntegerField(
        _('目标 QPS'), null=True, blank=True,
        help_text='可选，预留字段，限流在后续版本增强',
    )

    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        verbose_name = _('压测负载模型')
        verbose_name_plural = _('压测负载模型')

    def __str__(self):
        return f"{self.scenario.name} - {self.users} 用户"


class PerfTestExecution(models.Model):
    """执行记录，跟踪一次压测的生命周期"""

    STATUS_CHOICES = [
        ('pending', '待执行'),
        ('running', '执行中'),
        ('completed', '已完成'),
        ('failed', '失败'),
        ('canceled', '已取消'),
    ]

    scenario = models.ForeignKey(
        PerfTestScenario,
        on_delete=models.CASCADE,
        related_name='executions',
        verbose_name=_('所属场景'),
    )
    plan_snapshot = models.JSONField(_('负载参数快照'), default=dict, blank=True)
    status = models.CharField(
        _('状态'), max_length=20, choices=STATUS_CHOICES, default='pending'
    )
    progress = models.FloatField(_('进度(%)'), default=0)
    celery_task_id = models.CharField(_('Celery 任务 ID'), max_length=100, blank=True)
    error_message = models.TextField(_('错误信息'), blank=True)
    started_at = models.DateTimeField(_('开始时间'), null=True, blank=True)
    finished_at = models.DateTimeField(_('结束时间'), null=True, blank=True)
    executed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='perf_test_executions',
        verbose_name=_('执行人'),
    )
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)

    class Meta:
        verbose_name = _('压测执行记录')
        verbose_name_plural = _('压测执行记录')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['scenario', 'created_at'], name='perf_exec_scenario_created_idx'),
        ]

    def __str__(self):
        return f"{self.scenario.name}-{self.created_at.strftime('%Y%m%d%H%M%S')}"

    @property
    def project(self):
        return self.scenario.project if self.scenario else None

    @property
    def duration(self):
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0

    def start(self, celery_task_id=''):
        self.status = 'running'
        self.started_at = timezone.now()
        self.progress = 0
        self.error_message = ''
        if celery_task_id:
            self.celery_task_id = celery_task_id
        self.save()

    def update_progress(self, progress):
        self.progress = progress
        self.save(update_fields=['progress'])

    def complete(self):
        self.status = 'completed'
        self.finished_at = timezone.now()
        self.progress = 100
        self.save()

    def fail(self, error_message=''):
        self.status = 'failed'
        self.finished_at = timezone.now()
        self.error_message = error_message
        self.save()

    def cancel(self):
        self.status = 'canceled'
        self.finished_at = timezone.now()
        self.save()


class PerfTestReport(models.Model):
    """聚合报告，汇总一次执行的性能指标"""

    execution = models.OneToOneField(
        PerfTestExecution,
        on_delete=models.CASCADE,
        related_name='report',
        verbose_name=_('关联执行'),
    )
    total_requests = models.IntegerField(_('总请求数'), default=0)
    total_failures = models.IntegerField(_('失败请求数'), default=0)
    error_rate = models.FloatField(_('错误率(%)'), default=0)
    avg_response_time = models.FloatField(_('平均响应时间(ms)'), default=0)
    min_response_time = models.FloatField(_('最小响应时间(ms)'), default=0)
    max_response_time = models.FloatField(_('最大响应时间(ms)'), default=0)
    p50 = models.FloatField(_('P50(ms)'), default=0)
    p95 = models.FloatField(_('P95(ms)'), default=0)
    p99 = models.FloatField(_('P99(ms)'), default=0)
    total_rps = models.FloatField(_('平均 RPS'), default=0)
    peak_rps = models.FloatField(_('峰值 RPS'), default=0)
    rps_series = models.JSONField(_('RPS 时序'), default=list, blank=True)
    bottleneck_summary = models.JSONField(_('瓶颈快照'), default=dict, blank=True)

    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)

    class Meta:
        verbose_name = _('压测报告')
        verbose_name_plural = _('压测报告')
        ordering = ['-created_at']

    def __str__(self):
        return f"报告-{self.execution_id}"


class PerfTestNode(models.Model):
    """分布式施压节点，维护心跳与资源使用"""

    STATUS_CHOICES = [
        ('online', '在线'),
        ('offline', '离线'),
    ]

    name = models.CharField(_('节点名称'), max_length=200)
    host = models.CharField(_('节点地址'), max_length=200)
    status = models.CharField(
        _('状态'), max_length=20, choices=STATUS_CHOICES, default='online'
    )
    cpu_usage = models.FloatField(_('CPU 使用率(%)'), default=0)
    memory_usage = models.FloatField(_('内存使用率(%)'), default=0)
    last_heartbeat = models.DateTimeField(_('最后心跳时间'), null=True, blank=True)
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)

    class Meta:
        verbose_name = _('压测节点')
        verbose_name_plural = _('压测节点')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name}({self.host})"
