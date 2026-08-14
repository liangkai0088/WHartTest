from rest_framework import serializers

from .models import ExecutionEventLog


class ExecutionEventLogSerializer(serializers.ModelSerializer):
    """执行事件日志序列化器：{id, event_type, status, payload, created_at}"""

    class Meta:
        model = ExecutionEventLog
        fields = ["id", "event_type", "status", "payload", "created_at"]


class NodeSummarySerializer(serializers.Serializer):
    """泳道节点（TestCaseResult）摘要"""

    id = serializers.IntegerField()
    testcase_id = serializers.IntegerField()
    name = serializers.CharField()
    status = serializers.CharField()
    started_at = serializers.DateTimeField(allow_null=True, required=False)
    completed_at = serializers.DateTimeField(allow_null=True, required=False)
    execution_time = serializers.FloatField(allow_null=True, required=False)
    error_message = serializers.CharField(allow_null=True, required=False)


class RunSummarySerializer(serializers.Serializer):
    """TestExecution 汇总"""

    id = serializers.IntegerField()
    project_id = serializers.IntegerField()
    suite_id = serializers.IntegerField()
    suite_name = serializers.CharField()
    status = serializers.CharField()
    executor_id = serializers.IntegerField(allow_null=True, required=False)
    executor_name = serializers.CharField(allow_null=True, required=False)
    total_count = serializers.IntegerField()
    passed_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    skipped_count = serializers.IntegerField()
    error_count = serializers.IntegerField()
    pass_rate = serializers.FloatField()
    started_at = serializers.DateTimeField(allow_null=True, required=False)
    completed_at = serializers.DateTimeField(allow_null=True, required=False)
    duration = serializers.FloatField(allow_null=True, required=False)
    created_at = serializers.DateTimeField(required=False)


class EtaSerializer(serializers.Serializer):
    """ETA 估算"""

    eta_seconds = serializers.FloatField()
    remaining_seconds = serializers.FloatField()
    confidence = serializers.ChoiceField(choices=["high", "medium", "low"])
    progress = serializers.FloatField()


class RunSnapshotSerializer(serializers.Serializer):
    """执行快照：{run, nodes, eta}"""

    run = RunSummarySerializer()
    nodes = NodeSummarySerializer(many=True)
    eta = EtaSerializer()
