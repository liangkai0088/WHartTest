"""web_qa 模型定义。

平台化 AI Web QA 引擎：
- QaSuite       测试套件（midscene / agent_browser 双引擎）
- QaRun         单次执行
- QaBatchRun    批量/回归执行
- QaStepResult  逐步执行结果（渐进落库）
- AgentLocatorCache  agent 语义定位缓存
"""

from django.conf import settings
from django.db import models


class QaSuite(models.Model):
    """Web QA 测试套件。"""

    ENGINE_CHOICES = [
        ('midscene', 'Midscene 视觉引擎'),
        ('agent_browser', 'agent-browser 语义引擎'),
    ]
    SOURCE_CHOICES = [
        ('manual', '手动创建'),
        ('prd_generated', 'PRD 生成'),
    ]
    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('ready', '就绪'),
        ('generating', '生成中'),
    ]

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='web_qa_suites',
        verbose_name='所属项目',
    )
    name = models.CharField(max_length=200, verbose_name='套件名称')
    group = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name='分组',
        help_text='如 car_web',
    )
    engine = models.CharField(
        max_length=20, choices=ENGINE_CHOICES, default='agent_browser',
        verbose_name='执行引擎',
    )
    base_url = models.CharField(
        max_length=500, blank=True, default='', verbose_name='基础 URL',
    )
    description = models.TextField(blank=True, default='', verbose_name='描述')
    yaml_content = models.TextField(blank=True, default='', verbose_name='YAML 脚本')
    source = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default='manual',
        verbose_name='来源',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft',
        verbose_name='状态',
    )
    test_count = models.IntegerField(default=0, verbose_name='用例数')
    llm_config = models.ForeignKey(
        'langgraph_integration.LLMConfig',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='web_qa_suites',
        verbose_name='LLM 配置',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_web_qa_suites',
        verbose_name='创建人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'web_qa_qasuite'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', 'group']),
            models.Index(fields=['project', '-created_at']),
        ]

    def __str__(self):
        return f'{self.project.name} - {self.name} ({self.get_engine_display()})'


class QaBatchRun(models.Model):
    """批量 / 回归执行批次。"""

    STATUS_CHOICES = [
        ('pending', '待执行'),
        ('running', '执行中'),
        ('passed', '通过'),
        ('failed', '失败'),
        ('partial', '部分通过'),
        ('cancelled', '已取消'),
    ]

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='web_qa_batch_runs',
        verbose_name='所属项目',
    )
    name = models.CharField(max_length=200, verbose_name='批次名称')
    group = models.CharField(
        max_length=100, blank=True, default='', verbose_name='分组',
    )
    suite_ids = models.JSONField(default=list, blank=True, verbose_name='套件 ID 列表')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending',
        verbose_name='状态',
    )
    summary = models.JSONField(default=dict, blank=True, verbose_name='汇总')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_web_qa_batch_runs',
        verbose_name='创建人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'web_qa_qabatchrun'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.project.name} - {self.name}'


class QaRun(models.Model):
    """单次执行记录。"""

    STATUS_CHOICES = [
        ('pending', '待执行'),
        ('running', '执行中'),
        ('passed', '通过'),
        ('failed', '失败'),
        ('cancelled', '已取消'),
    ]

    suite = models.ForeignKey(
        QaSuite, on_delete=models.CASCADE, related_name='runs', verbose_name='套件',
    )
    batch = models.ForeignKey(
        QaBatchRun, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='runs', verbose_name='所属批次',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending',
        verbose_name='状态',
    )
    summary = models.JSONField(default=dict, blank=True, verbose_name='汇总')
    result_json = models.JSONField(default=dict, blank=True, verbose_name='结果 JSON')
    report_md = models.TextField(blank=True, default='', verbose_name='Markdown 报告')
    error = models.TextField(blank=True, default='', verbose_name='错误信息')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_web_qa_runs',
        verbose_name='创建人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'web_qa_qarun'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['suite', '-created_at']),
            models.Index(fields=['batch', '-created_at']),
        ]

    def __str__(self):
        return f'{self.suite.name} #{self.id} [{self.status}]'


class QaStepResult(models.Model):
    """步骤级执行结果（渐进保存）。"""

    STATUS_CHOICES = [
        ('pass', '通过'),
        ('fail', '失败'),
        ('skip', '跳过'),
        ('error', '错误'),
    ]

    run = models.ForeignKey(
        QaRun, on_delete=models.CASCADE, related_name='steps', verbose_name='执行',
    )
    test_index = models.IntegerField(default=0, verbose_name='用例序号')
    test_name = models.CharField(max_length=300, blank=True, default='', verbose_name='用例名称')
    step_index = models.IntegerField(default=0, verbose_name='步骤序号')
    action = models.CharField(max_length=300, blank=True, default='', verbose_name='动作')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pass', verbose_name='状态',
    )
    error = models.TextField(blank=True, default='', verbose_name='错误信息')
    screenshot_path = models.CharField(
        max_length=500, blank=True, default='', verbose_name='截图路径',
    )
    locator_meta = models.JSONField(default=dict, blank=True, verbose_name='定位元信息')
    duration_ms = models.IntegerField(default=0, verbose_name='耗时(ms)')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'web_qa_qastepresult'
        ordering = ['run_id', 'test_index', 'step_index']
        indexes = [
            models.Index(fields=['run', 'test_index', 'step_index']),
        ]

    def __str__(self):
        return f'run#{self.run_id} t{self.test_index}s{self.step_index} {self.action} [{self.status}]'


class AgentLocatorCache(models.Model):
    """agent 语义定位缓存：description -> selector。"""

    STRATEGY_CHOICES = [
        ('llm', 'LLM 视觉定位'),
        ('find', 'agent-browser find'),
        ('dom', 'DOM/快照降级'),
    ]

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='web_qa_locator_cache',
        verbose_name='所属项目',
    )
    base_url = models.CharField(max_length=500, blank=True, default='', verbose_name='基础 URL')
    description_hash = models.CharField(max_length=64, verbose_name='描述哈希')
    description = models.TextField(verbose_name='自然语言描述')
    selector = models.CharField(max_length=500, verbose_name='缓存选择器')
    strategy = models.CharField(
        max_length=20, choices=STRATEGY_CHOICES, default='llm', verbose_name='定位策略',
    )
    hits = models.IntegerField(default=0, verbose_name='命中次数')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'web_qa_agentlocatorcache'
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'base_url', 'description_hash'],
                name='uniq_web_qa_locator_cache',
            ),
        ]

    def __str__(self):
        return f'{self.description[:30]} [{self.strategy}] x{self.hits}'
