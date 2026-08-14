from rest_framework import serializers

from .models import CoverageReport, CoverageFile


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

    class Meta:
        model = CoverageReport
        fields = [
            'id', 'project', 'name', 'format', 'test_type',
            'test_execution_ref', 'git_commit', 'status', 'error_message',
            'summary', 'uploader', 'uploader_name', 'file_count', 'created_at',
        ]
        read_only_fields = [
            'id', 'status', 'error_message', 'summary', 'uploader', 'created_at',
        ]

    def get_file_count(self, obj):
        return obj.files.count()


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
