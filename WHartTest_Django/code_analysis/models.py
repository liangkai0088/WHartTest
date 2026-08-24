from django.db import models
from django.contrib.auth.models import User


class CodeProject(models.Model):
    """代码项目（zip 上传或 git 地址），隶属于业务项目。"""

    SOURCE_TYPE_CHOICES = [
        ('zip_upload', 'zip_upload'),
        ('git_url', 'git_url'),
    ]

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='code_projects',
        verbose_name='所属项目',
    )
    name = models.CharField(max_length=200, verbose_name='代码项目名称')
    source_type = models.CharField(
        max_length=20, choices=SOURCE_TYPE_CHOICES, default='zip_upload',
        verbose_name='来源类型',
    )
    git_url = models.CharField(max_length=1000, null=True, blank=True, verbose_name='Git 地址')
    repo_branch = models.CharField(max_length=200, null=True, blank=True, verbose_name='分支')
    current_snapshot = models.ForeignKey(
        'CodeProjectSnapshot',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='当前快照',
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_code_projects', verbose_name='创建人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'code_analysis_codeproject'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', '-created_at']),
        ]

    def __str__(self):
        return f'{self.project.name} - {self.name}'


class CodeProjectSnapshot(models.Model):
    """代码项目快照（一次 zip 上传 / 一次 git 拉取 = 一个快照）。"""

    code_project = models.ForeignKey(
        CodeProject, on_delete=models.CASCADE, related_name='snapshots',
        verbose_name='代码项目',
    )
    version_no = models.PositiveIntegerField(default=1, verbose_name='版本号')
    commit_ref = models.CharField(max_length=255, null=True, blank=True, verbose_name='Commit 引用')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_code_snapshots', verbose_name='创建人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'code_analysis_codeprojectsnapshot'
        ordering = ['-created_at']
        unique_together = [('code_project', 'version_no')]

    def __str__(self):
        return f'{self.code_project.name} v{self.version_no}'


class CodeFile(models.Model):
    """快照中的源码文件索引。"""

    snapshot = models.ForeignKey(
        CodeProjectSnapshot, on_delete=models.CASCADE, related_name='files',
        verbose_name='快照',
    )
    path = models.CharField(max_length=1000, verbose_name='文件路径')
    language = models.CharField(max_length=50, blank=True, default='', verbose_name='语言')
    sha256 = models.CharField(max_length=64, db_index=True, verbose_name='SHA256')
    size = models.IntegerField(default=0, verbose_name='文件大小')
    content = models.TextField(null=True, blank=True, verbose_name='文件内容')
    content_stored = models.BooleanField(default=False, verbose_name='内容已存储')
    is_deleted = models.BooleanField(default=False, verbose_name='已删除')

    class Meta:
        db_table = 'code_analysis_codefile'
        unique_together = [('snapshot', 'path')]
        indexes = [
            models.Index(fields=['snapshot', 'path']),
            models.Index(fields=['language']),
        ]

    def __str__(self):
        return f'{self.snapshot_id}:{self.path}'


class SpecAnalysisTask(models.Model):
    """OpenAPI 规范分析任务。"""

    STATUS_CHOICES = [
        ('pending', 'pending'),
        ('running', 'running'),
        ('completed', 'completed'),
        ('failed', 'failed'),
    ]
    SOURCE_CHOICES = [
        ('upload', 'upload'),
        ('spec_url', 'spec_url'),
    ]

    code_project = models.ForeignKey(
        CodeProject, on_delete=models.CASCADE, related_name='spec_analysis_tasks',
        verbose_name='代码项目',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='upload', verbose_name='来源')
    spec_name = models.CharField(max_length=255, blank=True, default='', verbose_name='Spec 名称/URL')
    use_llm = models.BooleanField(default=False, verbose_name='是否使用 LLM 增强')
    warnings = models.JSONField(default=list, blank=True, verbose_name='警告')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_spec_tasks', verbose_name='创建人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')

    class Meta:
        db_table = 'code_analysis_specanalysistask'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['code_project', 'status']),
        ]

    def __str__(self):
        return f'SpecAnalysisTask#{self.id} {self.status}'


class SpecAnalysisSuggestion(models.Model):
    """OpenAPI 分析产出的测试用例建议。"""

    STATUS_CHOICES = [
        ('pending', 'pending'),
        ('approved', 'approved'),
        ('rejected', 'rejected'),
        ('imported', 'imported'),
    ]

    task = models.ForeignKey(
        SpecAnalysisTask, on_delete=models.CASCADE, related_name='suggestions',
        verbose_name='分析任务',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    payload = models.JSONField(default=dict, verbose_name='建议内容')
    imported_interface_id = models.IntegerField(null=True, blank=True, verbose_name='导入的接口 ID')
    imported_testcase_id = models.IntegerField(null=True, blank=True, verbose_name='导入的用例 ID')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'code_analysis_specanalysissuggestion'
        ordering = ['id']
        indexes = [
            models.Index(fields=['task', 'status']),
        ]

    def __str__(self):
        name = (self.payload or {}).get('name') or f'#{self.id}'
        return f'Suggestion#{self.id} {name}'


class ComponentAnalysisTask(models.Model):
    """前端组件源码分析任务。"""

    STATUS_CHOICES = SpecAnalysisTask.STATUS_CHOICES

    code_project = models.ForeignKey(
        CodeProject, on_delete=models.CASCADE, related_name='component_analysis_tasks',
        verbose_name='代码项目',
    )
    snapshot = models.ForeignKey(
        CodeProjectSnapshot, on_delete=models.CASCADE, null=True, blank=True,
        related_name='component_analysis_tasks', verbose_name='快照',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    file_filter = models.JSONField(null=True, blank=True, verbose_name='文件过滤')
    warnings = models.JSONField(default=list, blank=True, verbose_name='警告')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_component_tasks', verbose_name='创建人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')

    class Meta:
        db_table = 'code_analysis_componentanalysistask'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['code_project', 'status']),
        ]

    def __str__(self):
        return f'ComponentAnalysisTask#{self.id} {self.status}'


class ElementSuggestion(models.Model):
    """组件分析产出的 UI 元素定位建议。"""

    STATUS_CHOICES = SpecAnalysisSuggestion.STATUS_CHOICES

    task = models.ForeignKey(
        ComponentAnalysisTask, on_delete=models.CASCADE, related_name='element_suggestions',
        verbose_name='分析任务',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    payload = models.JSONField(default=dict, verbose_name='建议内容')
    imported_page_id = models.IntegerField(null=True, blank=True, verbose_name='导入的页面 ID')
    imported_element_id = models.IntegerField(null=True, blank=True, verbose_name='导入的元素 ID')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'code_analysis_elementsuggestion'
        ordering = ['id']
        indexes = [
            models.Index(fields=['task', 'status']),
        ]

    def __str__(self):
        name = (self.payload or {}).get('element_name') or f'#{self.id}'
        return f'ElementSuggestion#{self.id} {name}'


class TestCodeLink(models.Model):
    """测试用例 <-> 源码 双向关联。

    - code_file：关联到具体快照的 CodeFile（快照源码）；
    - path：非快照来源（如 spec 文件）的路径兜底。
    两种来源至少其一（path 恒被填充，作为去重键）。
    """

    TESTCASE_TYPE_CHOICES = [
        ('functional', 'functional'),
        ('api', 'api'),
        ('ui', 'ui'),
    ]
    STATUS_CHOICES = [
        ('linked', 'linked'),
        ('outdated', 'outdated'),
    ]

    project = models.ForeignKey(
        'projects.Project', on_delete=models.CASCADE, related_name='code_links',
        verbose_name='所属项目',
    )
    testcase_type = models.CharField(max_length=20, choices=TESTCASE_TYPE_CHOICES, verbose_name='用例类型')
    testcase_id = models.IntegerField(verbose_name='用例 ID')
    code_file = models.ForeignKey(
        'CodeFile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='test_links', verbose_name='代码文件',
    )
    path = models.CharField(max_length=1000, null=True, blank=True, verbose_name='文件路径')
    symbol = models.CharField(max_length=255, null=True, blank=True, verbose_name='符号/名称')
    locator_ref = models.CharField(max_length=255, null=True, blank=True, verbose_name='定位器引用')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='linked', verbose_name='状态')
    last_verified_at = models.DateTimeField(null=True, blank=True, verbose_name='最近校验时间')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_test_code_links', verbose_name='创建人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'code_analysis_testcodelink'
        ordering = ['-updated_at']
        unique_together = [('project', 'testcase_type', 'testcase_id', 'path')]
        indexes = [
            models.Index(fields=['project', 'testcase_type', 'testcase_id']),
            models.Index(fields=['code_file']),
        ]

    def __str__(self):
        return f'{self.testcase_type}#{self.testcase_id} -> {self.path}'


class ChangeImpactRecord(models.Model):
    """代码变更对测试用例的影响记录（检测结果）。"""

    DIFF_STATUS_CHOICES = [
        ('added', 'added'),
        ('modified', 'modified'),
        ('deleted', 'deleted'),
    ]

    snapshot = models.ForeignKey(
        'CodeProjectSnapshot', on_delete=models.CASCADE, related_name='change_impacts',
        verbose_name='触发检测的快照',
    )
    code_file = models.ForeignKey(
        'CodeFile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='change_impacts', verbose_name='代码文件',
    )
    path = models.CharField(max_length=1000, null=True, blank=True, verbose_name='文件路径')
    testcase_type = models.CharField(max_length=20, choices=TestCodeLink.TESTCASE_TYPE_CHOICES, verbose_name='用例类型')
    testcase_id = models.IntegerField(verbose_name='用例 ID')
    diff_status = models.CharField(max_length=20, choices=DIFF_STATUS_CHOICES, verbose_name='变更类型')
    old_sha256 = models.CharField(max_length=64, null=True, blank=True, verbose_name='旧 SHA256')
    new_sha256 = models.CharField(max_length=64, null=True, blank=True, verbose_name='新 SHA256')
    size_delta = models.IntegerField(null=True, blank=True, verbose_name='大小变化')
    diff_summary = models.JSONField(default=dict, blank=True, verbose_name='行级差异摘要')
    resolved = models.BooleanField(default=False, verbose_name='已解决')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_change_impacts', verbose_name='创建人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'code_analysis_changeimpactrecord'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['snapshot', 'resolved']),
        ]

    def __str__(self):
        return f'{self.diff_status} {self.path} -> {self.testcase_type}#{self.testcase_id}'
