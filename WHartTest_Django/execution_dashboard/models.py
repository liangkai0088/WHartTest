from django.db import models


class ExecutionEventLog(models.Model):
    """
    AI执行进度事件日志。

    testcases.TestExecution 执行过程中的每个事件都记录一行，
    同时通过 WebSocket 推送。该模型是执行进度看板的数据源之一，
    与 testcases 现有模型完全解耦（仅通过 FK 关联）。
    """

    run = models.ForeignKey(
        "testcases.TestExecution",
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name="测试执行",
    )
    node_id = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="用例结果ID",
        help_text="对应的 TestCaseResult.id，非节点事件为空",
    )
    event_type = models.CharField(max_length=40, verbose_name="事件类型")
    status = models.CharField(
        max_length=20, blank=True, default="", verbose_name="节点状态"
    )
    payload = models.JSONField(default=dict, blank=True, verbose_name="事件负载")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "execution_event_log"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["run", "created_at"], name="exec_evt_run_created_idx"),
        ]
        verbose_name = "执行事件日志"
        verbose_name_plural = "执行事件日志"

    def __str__(self):
        return f"run={self.run_id} {self.event_type} ({self.created_at})"
