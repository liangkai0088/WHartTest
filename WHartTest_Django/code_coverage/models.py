import uuid

from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _

from projects.models import Project


class CoverageReport(models.Model):
    """覆盖率报告批次，对应一次测试执行的上报"""

    FORMAT_CHOICES = [
        ('cobertura', 'Cobertura XML'),
        ('lcov', 'LCOV'),
    ]
    TEST_TYPE_CHOICES = [
        ('api', '接口自动化'),
        ('ui', 'UI 自动化'),
        ('unit', '单元测试'),
        ('manual', '手工测试'),
    ]
    STATUS_CHOICES = [
        ('processing', '处理中'),
        ('completed', '已完成'),
        ('failed', '失败'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='coverage_reports',
        verbose_name=_('所属项目'),
    )
    name = models.CharField(_('报告名称'), max_length=200)
    format = models.CharField(_('报告格式'), max_length=20, choices=FORMAT_CHOICES)
    test_type = models.CharField(
        _('测试类型'), max_length=20, choices=TEST_TYPE_CHOICES, default='api'
    )
    test_execution_ref = models.CharField(
        _('关联测试执行'), max_length=200, blank=True, null=True,
        help_text='关联的测试执行记录标识',
    )
    git_commit = models.CharField(
        _('Git Commit'), max_length=64, blank=True, null=True
    )

    status = models.CharField(
        _('状态'), max_length=20, choices=STATUS_CHOICES, default='processing'
    )
    error_message = models.TextField(_('错误信息'), blank=True, null=True)

    # 汇总指标
    summary = models.JSONField(_('汇总指标'), default=dict, blank=True)

    uploader = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_coverage_reports',
        verbose_name=_('上传人'),
    )
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)

    class Meta:
        verbose_name = _('覆盖率报告')
        verbose_name_plural = _('覆盖率报告')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', 'created_at'], name='cov_report_proj_created_idx'),
        ]

    def __str__(self):
        return f"{self.project.name} - {self.name}"


class CoverageFile(models.Model):
    """文件级覆盖率明细"""

    report = models.ForeignKey(
        CoverageReport,
        on_delete=models.CASCADE,
        related_name='files',
        verbose_name=_('所属报告'),
    )
    file_path = models.CharField(_('文件路径'), max_length=500)
    line_coverage = models.FloatField(_('行覆盖率(%)'), default=0)
    branch_coverage = models.FloatField(_('分支覆盖率(%)'), null=True, blank=True)
    lines_total = models.IntegerField(_('总行数'), default=0)
    lines_covered = models.IntegerField(_('覆盖行数'), default=0)
    # 行级明细：{行号字符串: 命中次数}
    lines_detail = models.JSONField(_('行级明细'), default=dict, blank=True)

    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)

    class Meta:
        verbose_name = _('覆盖率文件明细')
        verbose_name_plural = _('覆盖率文件明细')
        ordering = ['file_path']
        indexes = [
            models.Index(fields=['report', 'file_path'], name='cov_file_report_path_idx'),
        ]

    def __str__(self):
        return f"{self.file_path} ({self.line_coverage:.1f}%)"


class CoverageDelta(models.Model):
    """增量覆盖率：一次提交相对基线的覆盖变化"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='coverage_deltas',
        verbose_name=_('所属项目'),
    )
    report = models.ForeignKey(
        CoverageReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deltas',
        verbose_name=_('当前提交报告'),
    )
    base_report = models.ForeignKey(
        CoverageReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='base_deltas',
        verbose_name=_('基线报告'),
    )
    git_commit = models.CharField(_('Git Commit'), max_length=64)
    base_commit = models.CharField(_('基线 Commit'), max_length=64, blank=True, null=True)

    # 增量汇总指标
    summary = models.JSONField(_('增量汇总'), default=dict, blank=True)
    # 文件级增量明细：[{file_path, status, new_lines, covered_new_lines, delta_coverage, removed_lines}]
    files = models.JSONField(_('文件级增量明细'), default=list, blank=True)

    uploader = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_coverage_deltas',
        verbose_name=_('生成人'),
    )
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)

    class Meta:
        verbose_name = _('增量覆盖率')
        verbose_name_plural = _('增量覆盖率')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', 'git_commit'], name='cov_delta_proj_commit_idx'),
        ]

    def __str__(self):
        return f"{self.git_commit[:8]} - {self.summary.get('delta_coverage', 0)}%"
