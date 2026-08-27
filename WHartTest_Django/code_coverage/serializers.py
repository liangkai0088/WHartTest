from rest_framework import serializers

from .models import CoverageReport, CoverageFile, CoverageDelta, CoverageGateConfig


class CoverageFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoverageFile
        fields = [
            'id', 'file_path', 'line_coverage', 'branch_coverage',
            'lines_total', 'lines_covered', 'lines_detail',
        ]


class CoverageReportSerializer(serializers.ModelSerializer):
    uploader_name = serializers.CharField(source='uploader.username', read_only=True)
    file_count = serializers.SerializerMethodField()
    gate = serializers.SerializerMethodField()

    class Meta:
        model = CoverageReport
        fields = [
            'id', 'project', 'name', 'format', 'test_type',
            'test_execution_ref', 'git_commit', 'status', 'error_message',
            'summary', 'uploader', 'uploader_name', 'file_count', 'gate', 'created_at',
        ]
        read_only_fields = [
            'id', 'status', 'error_message', 'summary', 'uploader', 'created_at',
        ]

    def get_file_count(self, obj):
        return obj.files.count()

    def get_gate(self, obj):
        try:
            gate = obj.project.coverage_gate
        except CoverageGateConfig.DoesNotExist:
            return {'enabled': False, 'passed': None}
        if not gate.enabled:
            return {'enabled': False, 'passed': None}
        actual = (obj.summary or {}).get('line_coverage') or 0
        return {
            'enabled': True,
            'threshold': gate.min_line_coverage,
            'actual': actual,
            'passed': actual >= gate.min_line_coverage,
        }


class CoverageUploadSerializer(serializers.Serializer):
    """覆盖率报告上传参数"""

    project_id = serializers.IntegerField(help_text='所属项目 ID')
    name = serializers.CharField(max_length=200)
    format = serializers.ChoiceField(choices=['cobertura', 'lcov'])
    test_type = serializers.ChoiceField(
        choices=['api', 'ui', 'unit', 'manual'], default='api', required=False
    )
    test_execution_ref = serializers.CharField(
        max_length=200, required=False, allow_blank=True, allow_null=True
    )
    git_commit = serializers.CharField(
        max_length=64, required=False, allow_blank=True, allow_null=True
    )
    file = serializers.FileField()


class CoverageDeltaSerializer(serializers.ModelSerializer):
    uploader_name = serializers.CharField(source='uploader.username', read_only=True)

    class Meta:
        model = CoverageDelta
        fields = [
            'id', 'project', 'report', 'base_report', 'git_commit', 'base_commit',
            'summary', 'files', 'uploader', 'uploader_name', 'created_at',
        ]
        read_only_fields = [
            'id', 'project', 'report', 'base_report', 'summary', 'files',
            'uploader', 'created_at',
        ]


class CoverageGateConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoverageGateConfig
        fields = [
            'id', 'project', 'enabled', 'min_line_coverage', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'project', 'created_at', 'updated_at']
