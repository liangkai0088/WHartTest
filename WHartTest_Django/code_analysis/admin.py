from django.contrib import admin

from .models import (
    ChangeImpactRecord,
    CodeFile,
    CodeProject,
    CodeProjectSnapshot,
    ComponentAnalysisTask,
    ElementSuggestion,
    SpecAnalysisSuggestion,
    SpecAnalysisTask,
    TestCodeLink,
)


@admin.register(CodeProject)
class CodeProjectAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'project', 'source_type', 'current_snapshot', 'created_by', 'created_at')
    list_filter = ('source_type', 'created_at')
    search_fields = ('name', 'git_url')


@admin.register(CodeProjectSnapshot)
class CodeProjectSnapshotAdmin(admin.ModelAdmin):
    list_display = ('id', 'code_project', 'version_no', 'commit_ref', 'created_by', 'created_at')
    list_filter = ('created_at',)


@admin.register(CodeFile)
class CodeFileAdmin(admin.ModelAdmin):
    list_display = ('id', 'snapshot', 'path', 'language', 'size', 'content_stored', 'is_deleted')
    list_filter = ('language', 'content_stored', 'is_deleted')
    search_fields = ('path', 'sha256')
    raw_id_fields = ('snapshot',)


@admin.register(SpecAnalysisTask)
class SpecAnalysisTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'code_project', 'status', 'source', 'spec_name', 'use_llm', 'created_by', 'created_at', 'finished_at')
    list_filter = ('status', 'source', 'use_llm', 'created_at')


@admin.register(SpecAnalysisSuggestion)
class SpecAnalysisSuggestionAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'status', 'imported_interface_id', 'imported_testcase_id', 'created_at')
    list_filter = ('status',)


@admin.register(ComponentAnalysisTask)
class ComponentAnalysisTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'code_project', 'snapshot', 'status', 'created_by', 'created_at', 'finished_at')
    list_filter = ('status', 'created_at')


@admin.register(ElementSuggestion)
class ElementSuggestionAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'status', 'imported_page_id', 'imported_element_id', 'created_at')
    list_filter = ('status',)


@admin.register(TestCodeLink)
class TestCodeLinkAdmin(admin.ModelAdmin):
    list_display = ('id', 'project', 'testcase_type', 'testcase_id', 'path', 'status', 'last_verified_at')
    list_filter = ('testcase_type', 'status')
    search_fields = ('path', 'symbol')


@admin.register(ChangeImpactRecord)
class ChangeImpactRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'snapshot', 'path', 'testcase_type', 'testcase_id', 'diff_status', 'resolved', 'created_at')
    list_filter = ('diff_status', 'resolved')
    search_fields = ('path',)
