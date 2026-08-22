from rest_framework import serializers

from .models import (
    PerfTestScenario,
    PerfTestRequest,
    PerfTestPlan,
    PerfTestExecution,
    PerfTestReport,
    PerfTestNode,
)


class PerfTestRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerfTestRequest
        fields = [
            'id', 'scenario', 'name', 'method', 'url', 'headers', 'params',
            'body', 'variables', 'validators', 'weight', 'order', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class PerfTestPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerfTestPlan
        fields = [
            'id', 'scenario', 'users', 'spawn_rate', 'duration',
            'think_time', 'target_qps', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PerfTestScenarioSerializer(serializers.ModelSerializer):
    requests = PerfTestRequestSerializer(many=True, read_only=True)
    plan = serializers.SerializerMethodField()
    request_count = serializers.SerializerMethodField()
    creator_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = PerfTestScenario
        fields = [
            'id', 'name', 'description', 'source', 'project', 'locustfile',
            'requests', 'plan', 'request_count', 'creator_name', 'created_by',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'locustfile', 'created_by', 'created_at', 'updated_at']

    def get_request_count(self, obj):
        return len(obj.requests.all())

    def get_plan(self, obj):
        try:
            plan = obj.plan
        except PerfTestPlan.DoesNotExist:
            return None
        return PerfTestPlanSerializer(plan).data


class PerfTestExecutionSerializer(serializers.ModelSerializer):
    scenario_name = serializers.CharField(source='scenario.name', read_only=True)
    executed_by_name = serializers.CharField(source='executed_by.username', read_only=True)
    report_id = serializers.SerializerMethodField()

    class Meta:
        model = PerfTestExecution
        fields = [
            'id', 'scenario', 'scenario_name', 'plan_snapshot', 'status',
            'progress', 'celery_task_id', 'error_message', 'started_at',
            'finished_at', 'executed_by', 'executed_by_name', 'report_id',
            'created_at',
        ]
        read_only_fields = [
            'id', 'plan_snapshot', 'status', 'progress', 'celery_task_id',
            'error_message', 'started_at', 'finished_at', 'executed_by', 'created_at',
        ]

    def get_report_id(self, obj):
        try:
            return obj.report.id
        except PerfTestReport.DoesNotExist:
            return None


class PerfTestReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerfTestReport
        fields = [
            'id', 'execution', 'total_requests', 'total_failures', 'error_rate',
            'avg_response_time', 'min_response_time', 'max_response_time',
            'p50', 'p95', 'p99', 'total_rps', 'peak_rps', 'rps_series',
            'bottleneck_summary', 'created_at',
        ]
        read_only_fields = fields


class PerfTestNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerfTestNode
        fields = [
            'id', 'name', 'host', 'status', 'cpu_usage', 'memory_usage',
            'last_heartbeat', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']
