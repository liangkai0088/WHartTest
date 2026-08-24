from rest_framework import serializers
from django.db.models import Count

from .linkage import resolve_testcase_name
from .models import (
    ChangeImpactRecord,
    CodeProject,
    CodeFile,
    ComponentAnalysisTask,
    ElementSuggestion,
    SpecAnalysisTask,
    SpecAnalysisSuggestion,
    TestCodeLink,
)


class CodeProjectSerializer(serializers.ModelSerializer):
    latest_snapshot = serializers.SerializerMethodField()

    class Meta:
        model = CodeProject
        fields = [
            'id', 'project', 'name', 'source_type', 'git_url', 'repo_branch',
            'current_snapshot', 'latest_snapshot', 'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['project', 'created_by', 'created_at', 'updated_at', 'current_snapshot']

    def get_latest_snapshot(self, obj):
        snap = obj.snapshots.order_by('-version_no').first()
        if snap is None:
            return None
        return {
            'id': snap.id,
            'version_no': snap.version_no,
            'commit_ref': snap.commit_ref,
            'status': 'pending' if snap.commit_ref == 'pending' else 'completed',
        }


class CodeFileListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CodeFile
        fields = ['id', 'path', 'language', 'size', 'sha256', 'content_stored']


class SpecAnalysisSuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpecAnalysisSuggestion
        fields = [
            'id', 'status', 'payload', 'imported_interface_id',
            'imported_testcase_id', 'created_at',
        ]


class SpecAnalysisTaskSerializer(serializers.ModelSerializer):
    suggestion_counts = serializers.SerializerMethodField()

    class Meta:
        model = SpecAnalysisTask
        fields = [
            'id', 'code_project', 'status', 'source', 'spec_name', 'use_llm',
            'warnings', 'created_at', 'finished_at', 'suggestion_counts',
        ]
        read_only_fields = ['status', 'warnings', 'created_at', 'finished_at']

    def get_suggestion_counts(self, obj):
        counts = obj.suggestions.values('status').annotate(c=Count('id'))
        return {x['status']: x['c'] for x in counts}


class ElementSuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ElementSuggestion
        fields = [
            'id', 'status', 'payload', 'imported_page_id',
            'imported_element_id', 'created_at',
        ]


class ComponentAnalysisTaskSerializer(serializers.ModelSerializer):
    element_suggestion_counts = serializers.SerializerMethodField()

    class Meta:
        model = ComponentAnalysisTask
        fields = [
            'id', 'code_project', 'snapshot', 'status', 'file_filter',
            'warnings', 'created_at', 'finished_at', 'element_suggestion_counts',
        ]
        read_only_fields = ['status', 'warnings', 'created_at', 'finished_at']

    def get_element_suggestion_counts(self, obj):
        counts = obj.element_suggestions.values('status').annotate(c=Count('id'))
        return {x['status']: x['c'] for x in counts}


class TestCodeLinkSerializer(serializers.ModelSerializer):
    testcase_name = serializers.SerializerMethodField()
    code_file_path = serializers.SerializerMethodField()

    class Meta:
        model = TestCodeLink
        fields = [
            'id', 'project', 'testcase_type', 'testcase_id', 'testcase_name',
            'code_file', 'code_file_path', 'path', 'symbol', 'locator_ref',
            'status', 'last_verified_at', 'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['project', 'status', 'last_verified_at', 'created_by', 'created_at', 'updated_at']

    def get_testcase_name(self, obj):
        return resolve_testcase_name(obj.testcase_type, obj.testcase_id)

    def get_code_file_path(self, obj):
        if obj.code_file_id:
            return obj.code_file.path if obj.code_file else None
        return obj.path


class ChangeImpactRecordSerializer(serializers.ModelSerializer):
    testcase_name = serializers.SerializerMethodField()
    code_file_path = serializers.SerializerMethodField()

    class Meta:
        model = ChangeImpactRecord
        fields = [
            'id', 'snapshot', 'code_file', 'code_file_path', 'path',
            'testcase_type', 'testcase_id', 'testcase_name', 'diff_status',
            'old_sha256', 'new_sha256', 'size_delta', 'diff_summary', 'resolved',
            'created_by', 'created_at',
        ]
        read_only_fields = fields

    def get_testcase_name(self, obj):
        return resolve_testcase_name(obj.testcase_type, obj.testcase_id)

    def get_code_file_path(self, obj):
        if obj.code_file_id:
            return obj.code_file.path if obj.code_file else None
        return obj.path
