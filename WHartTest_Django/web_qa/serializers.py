"""web_qa DRF 序列化器。"""

from rest_framework import serializers

from .models import AgentLocatorCache, QaBatchRun, QaRun, QaStepResult, QaSuite


class QaSuiteSerializer(serializers.ModelSerializer):
    llm_config_name = serializers.SerializerMethodField()
    run_count = serializers.SerializerMethodField()

    class Meta:
        model = QaSuite
        fields = [
            'id', 'project', 'name', 'group', 'engine', 'base_url', 'description',
            'yaml_content', 'source', 'status', 'test_count', 'llm_config',
            'llm_config_name', 'run_count', 'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['project', 'source', 'status', 'test_count', 'created_by', 'created_at', 'updated_at']

    def get_llm_config_name(self, obj):
        if obj.llm_config is None:
            return None
        return str(obj.llm_config)

    def get_run_count(self, obj):
        return obj.runs.count()


class QaSuiteListSerializer(serializers.ModelSerializer):
    """列表视图（不含 yaml_content 大字段）。"""

    class Meta:
        model = QaSuite
        fields = [
            'id', 'name', 'group', 'engine', 'base_url', 'description',
            'source', 'status', 'test_count', 'llm_config', 'created_by',
            'created_at', 'updated_at',
        ]


class QaRunSerializer(serializers.ModelSerializer):
    suite_name = serializers.CharField(source='suite.name', read_only=True)
    suite_engine = serializers.CharField(source='suite.engine', read_only=True)
    suite_id = serializers.IntegerField(source='suite.id', read_only=True)
    step_count = serializers.SerializerMethodField()

    class Meta:
        model = QaRun
        fields = [
            'id', 'suite', 'suite_id', 'suite_name', 'suite_engine', 'batch',
            'status', 'summary', 'result_json', 'report_md', 'error',
            'started_at', 'finished_at', 'created_by', 'created_at', 'step_count',
        ]
        read_only_fields = fields

    def get_step_count(self, obj):
        return obj.steps.count()


class QaRunListSerializer(QaRunSerializer):
    class Meta(QaRunSerializer.Meta):
        fields = [
            'id', 'suite', 'suite_id', 'suite_name', 'suite_engine', 'batch',
            'status', 'summary', 'error', 'started_at', 'finished_at',
            'created_by', 'created_at', 'step_count',
        ]


class QaStepResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = QaStepResult
        fields = [
            'id', 'run', 'test_index', 'test_name', 'step_index', 'action',
            'status', 'error', 'screenshot_path', 'locator_meta', 'duration_ms',
            'created_at',
        ]
        read_only_fields = fields


class QaBatchRunSerializer(serializers.ModelSerializer):
    runs = QaRunListSerializer(many=True, read_only=True)

    class Meta:
        model = QaBatchRun
        fields = [
            'id', 'project', 'name', 'group', 'suite_ids', 'status', 'summary',
            'created_by', 'created_at', 'updated_at', 'runs',
        ]
        read_only_fields = ['project', 'status', 'summary', 'created_by', 'created_at', 'updated_at']


class AgentLocatorCacheSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentLocatorCache
        fields = [
            'id', 'project', 'base_url', 'description_hash', 'description',
            'selector', 'strategy', 'hits', 'created_at', 'updated_at',
        ]
        read_only_fields = fields
